from typing import Any, Optional, cast

from azure.search.documents.agent.aio import KnowledgeAgentRetrievalClient
from azure.search.documents.aio import SearchClient
from azure.search.documents.models import VectorQuery
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam

from approaches.approach import (
    Approach, 
    DataPoints, 
    DocumentLabelInfo, 
    ExtraInfo, 
    ResponseSensitivityInfo, 
    SensitivityLabelInfo, 
    ThoughtStep
)
from approaches.promptmanager import PromptManager
from core.authentication import AuthenticationHelper
from core.labelhelper import LabelHelper


class RetrieveThenReadApproach(Approach):
    """
    Simple retrieve-then-read implementation, using the AI Search and OpenAI APIs directly. It first retrieves
    top documents from search, then constructs a prompt with them, and then uses OpenAI to generate an completion
    (answer) with that prompt.
    """

    def __init__(
        self,
        *,
        search_client: SearchClient,
        search_index_name: str,
        agent_model: Optional[str],
        agent_deployment: Optional[str],
        agent_client: KnowledgeAgentRetrievalClient,
        auth_helper: AuthenticationHelper,
        openai_client: AsyncOpenAI,
        chatgpt_model: str,
        chatgpt_deployment: Optional[str],  # Not needed for non-Azure OpenAI
        embedding_model: str,
        embedding_deployment: Optional[str],  # Not needed for non-Azure OpenAI or for retrieval_mode="text"
        embedding_dimensions: int,
        embedding_field: str,
        sourcepage_field: str,
        content_field: str,
        query_language: str,
        query_speller: str,
        prompt_manager: PromptManager,
        reasoning_effort: Optional[str] = None,
    ):
        self.search_client = search_client
        self.search_index_name = search_index_name
        self.agent_model = agent_model
        self.agent_deployment = agent_deployment
        self.agent_client = agent_client
        self.chatgpt_deployment = chatgpt_deployment
        self.openai_client = openai_client
        self.auth_helper = auth_helper
        self.chatgpt_model = chatgpt_model
        self.embedding_model = embedding_model
        self.embedding_dimensions = embedding_dimensions
        self.chatgpt_deployment = chatgpt_deployment
        self.embedding_deployment = embedding_deployment
        self.embedding_field = embedding_field
        self.sourcepage_field = sourcepage_field
        self.content_field = content_field
        self.query_language = query_language
        self.query_speller = query_speller
        self.prompt_manager = prompt_manager
        self.answer_prompt = self.prompt_manager.load_prompt("ask_answer_question.prompty")
        self.reasoning_effort = reasoning_effort
        self.include_token_usage = True
        self.label_helper = LabelHelper()

    async def run(
        self,
        messages: list[ChatCompletionMessageParam],
        session_state: Any = None,
        context: dict[str, Any] = {},
    ) -> dict[str, Any]:
        overrides = context.get("overrides", {})
        auth_claims = context.get("auth_claims", {})
        use_agentic_retrieval = True if overrides.get("use_agentic_retrieval") else False
        q = messages[-1]["content"]
        if not isinstance(q, str):
            raise ValueError("The most recent message content must be a string.")

        if use_agentic_retrieval:
            extra_info = await self.run_agentic_retrieval_approach(messages, overrides, auth_claims)
        else:
            extra_info = await self.run_search_approach(messages, overrides, auth_claims)

        # Process results
        messages = self.prompt_manager.render_prompt(
            self.answer_prompt,
            self.get_system_prompt_variables(overrides.get("prompt_template"))
            | {"user_query": q, "text_sources": extra_info.data_points.text},
        )

        chat_completion = cast(
            ChatCompletion,
            await self.create_chat_completion(
                self.chatgpt_deployment,
                self.chatgpt_model,
                messages=messages,
                overrides=overrides,
                response_token_limit=self.get_response_token_limit(self.chatgpt_model, 1024),
            ),
        )
        extra_info.thoughts.append(
            self.format_thought_step_for_chatcompletion(
                title="Prompt to generate answer",
                messages=messages,
                overrides=overrides,
                model=self.chatgpt_model,
                deployment=self.chatgpt_deployment,
                usage=chat_completion.usage,
            )
        )
        return {
            "message": {
                "content": chat_completion.choices[0].message.content,
                "role": chat_completion.choices[0].message.role,
            },
            "context": {
                "data_points": extra_info.data_points.text,
                "thoughts": extra_info.thoughts,
                "followup_questions": extra_info.followup_questions,
                "sensitivity": extra_info.data_points.sensitivity,  # Extract sensitivity to context level
            },
            "session_state": session_state,
        }

    async def run_search_approach(
        self, messages: list[ChatCompletionMessageParam], overrides: dict[str, Any], auth_claims: dict[str, Any]
    ):
        use_text_search = overrides.get("retrieval_mode") in ["text", "hybrid", None]
        use_vector_search = overrides.get("retrieval_mode") in ["vectors", "hybrid", None]
        use_semantic_ranker = True if overrides.get("semantic_ranker") else False
        use_query_rewriting = True if overrides.get("query_rewriting") else False
        use_semantic_captions = True if overrides.get("semantic_captions") else False
        top = overrides.get("top", 3)
        minimum_search_score = overrides.get("minimum_search_score", 0.0)
        minimum_reranker_score = overrides.get("minimum_reranker_score", 0.0)
        filter = self.build_filter(overrides, auth_claims)
        q = str(messages[-1]["content"])

        # If retrieval mode includes vectors, compute an embedding for the query
        vectors: list[VectorQuery] = []
        if use_vector_search:
            vectors.append(await self.compute_text_embedding(q))

        results = await self.search(
            top,
            q,
            filter,
            vectors,
            use_text_search,
            use_vector_search,
            use_semantic_ranker,
            use_semantic_captions,
            minimum_search_score,
            minimum_reranker_score,
            use_query_rewriting,
        )

        text_sources = self.get_sources_content(results, use_semantic_captions, use_image_citation=False)
        
        # Process sensitivity labels from search results
        sensitivity_info = await self._process_sensitivity_labels(results, auth_claims)

        return ExtraInfo(
            DataPoints(text=text_sources, sensitivity=sensitivity_info),
            thoughts=[
                ThoughtStep(
                    "Search using user query",
                    q,
                    {
                        "use_semantic_captions": use_semantic_captions,
                        "use_semantic_ranker": use_semantic_ranker,
                        "use_query_rewriting": use_query_rewriting,
                        "top": top,
                        "filter": filter,
                        "use_vector_search": use_vector_search,
                        "use_text_search": use_text_search,
                    },
                ),
                ThoughtStep(
                    "Search results",
                    [result.serialize_for_results() for result in results],
                ),
            ],
        )

    async def run_agentic_retrieval_approach(
        self,
        messages: list[ChatCompletionMessageParam],
        overrides: dict[str, Any],
        auth_claims: dict[str, Any],
    ):
        minimum_reranker_score = overrides.get("minimum_reranker_score", 0)
        search_index_filter = self.build_filter(overrides, auth_claims)
        top = overrides.get("top", 3)
        max_subqueries = overrides.get("max_subqueries", 10)
        results_merge_strategy = overrides.get("results_merge_strategy", "interleaved")
        # 50 is the amount of documents that the reranker can process per query
        max_docs_for_reranker = max_subqueries * 50

        response, results = await self.run_agentic_retrieval(
            messages,
            self.agent_client,
            search_index_name=self.search_index_name,
            top=top,
            filter_add_on=search_index_filter,
            minimum_reranker_score=minimum_reranker_score,
            max_docs_for_reranker=max_docs_for_reranker,
            results_merge_strategy=results_merge_strategy,
        )

        text_sources = self.get_sources_content(results, use_semantic_captions=False, use_image_citation=False)
        
        # Process sensitivity labels from search results
        sensitivity_info = await self._process_sensitivity_labels(results, auth_claims)

        extra_info = ExtraInfo(
            DataPoints(text=text_sources, sensitivity=sensitivity_info),
            thoughts=[
                ThoughtStep(
                    "Use agentic retrieval",
                    messages,
                    {
                        "reranker_threshold": minimum_reranker_score,
                        "max_docs_for_reranker": max_docs_for_reranker,
                        "results_merge_strategy": results_merge_strategy,
                        "filter": search_index_filter,
                    },
                ),
                ThoughtStep(
                    f"Agentic retrieval results (top {top})",
                    [result.serialize_for_results() for result in results],
                    {
                        "query_plan": (
                            [activity.as_dict() for activity in response.activity] if response.activity else None
                        ),
                        "model": self.agent_model,
                        "deployment": self.agent_deployment,
                    },
                ),
            ],
        )
        return extra_info

    async def _process_sensitivity_labels(self, results, auth_claims: dict[str, Any]) -> Optional[ResponseSensitivityInfo]:
        """Process sensitivity labels from search results and compute response sensitivity."""
        try:
            
            # Convert search results to dictionaries for label helper processing
            search_results_dicts = []
            for i, result in enumerate(results):
                
                result_dict = {
                    "id": getattr(result, "id", "unknown"),
                    "sourcefile": getattr(result, "sourcefile", getattr(result, "sourcepage", "unknown")),
                    "metadata_storage_name": getattr(result, "sourcefile", getattr(result, "sourcepage", "unknown")),
                    "metadata_sensitivity_label": getattr(result, "metadata_sensitivity_label", None),
                }
                search_results_dicts.append(result_dict)
                        
            # Extract user's Graph access token for delegated label resolution
            user_graph_token = auth_claims.get("graph_access_token")

            
            document_labels = await self.label_helper.extract_labels_from_search_results(search_results_dicts, user_graph_token)
            
            if not document_labels:
                return None
                
            # Compute response sensitivity with user token for Graph API inheritance
            response_sensitivity = await self.label_helper.compute_label_inheritance(document_labels, user_graph_token)
            
            if not response_sensitivity:
                return None
            
            # Convert to frontend format
            document_label_infos = []
            for doc_label in response_sensitivity.document_labels:
                badge_info = self.label_helper.get_sensitivity_badge_info(doc_label.label)
                label_info = SensitivityLabelInfo(
                    id=doc_label.label.id,
                    name=doc_label.label.name,
                    display_name=doc_label.label.display_name,
                    color=badge_info["color"],
                    icon=badge_info["icon"]
                )
                document_label_infos.append(DocumentLabelInfo(
                    document_id=doc_label.document_id,
                    source_file=doc_label.source_file,
                    label=label_info
                ))
            
            # Create overall response sensitivity info
            overall_badge_info = self.label_helper.get_sensitivity_badge_info(response_sensitivity.overall_label)
            overall_label_info = SensitivityLabelInfo(
                id=response_sensitivity.overall_label.id,
                name=response_sensitivity.overall_label.name,
                display_name=response_sensitivity.overall_label.display_name,
                color=overall_badge_info["color"],
                icon=overall_badge_info["icon"]
            )
            
            return ResponseSensitivityInfo(
                overall_label=overall_label_info,
                document_labels=document_label_infos
            )
            
        except Exception as e:
            # Log error but don't fail the whole request
            import logging
            logging.getLogger(__name__).warning(f"Failed to process sensitivity labels: {e}")
            return None
