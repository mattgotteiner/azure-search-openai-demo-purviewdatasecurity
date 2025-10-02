from collections.abc import Awaitable
from typing import Any, Optional, Union, cast

from azure.search.documents.agent.aio import KnowledgeAgentRetrievalClient
from azure.search.documents.aio import SearchClient
from azure.search.documents.models import VectorQuery
from openai import AsyncOpenAI, AsyncStream
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionChunk,
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
)

from approaches.approach import (
    DataPoints, 
    DocumentLabelInfo, 
    ExtraInfo, 
    ResponseSensitivityInfo, 
    SensitivityLabelInfo, 
    ThoughtStep
)
from approaches.chatapproach import ChatApproach
from approaches.promptmanager import PromptManager
from core.authentication import AuthenticationHelper
from core.labelhelper import LabelHelper


class ChatReadRetrieveReadApproach(ChatApproach):
    """
    A multi-step approach that first uses OpenAI to turn the user's question into a search query,
    then uses Azure AI Search to retrieve relevant documents, and then sends the conversation history,
    original user question, and search results to OpenAI to generate a response.
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
        embedding_deployment: Optional[str],  # Not needed for non-Azure OpenAI or for retrieval_mode="text"
        embedding_model: str,
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
        self.openai_client = openai_client
        self.auth_helper = auth_helper
        self.chatgpt_model = chatgpt_model
        self.chatgpt_deployment = chatgpt_deployment
        self.embedding_deployment = embedding_deployment
        self.embedding_model = embedding_model
        self.embedding_dimensions = embedding_dimensions
        self.embedding_field = embedding_field
        self.sourcepage_field = sourcepage_field
        self.content_field = content_field
        self.query_language = query_language
        self.query_speller = query_speller
        self.prompt_manager = prompt_manager
        self.query_rewrite_prompt = self.prompt_manager.load_prompt("chat_query_rewrite.prompty")
        self.query_rewrite_tools = self.prompt_manager.load_tools("chat_query_rewrite_tools.json")
        self.answer_prompt = self.prompt_manager.load_prompt("chat_answer_question.prompty")
        self.reasoning_effort = reasoning_effort
        self.include_token_usage = True
        self.label_helper = LabelHelper()

    async def run_until_final_call(
        self,
        messages: list[ChatCompletionMessageParam],
        overrides: dict[str, Any],
        auth_claims: dict[str, Any],
        should_stream: bool = False,
    ) -> tuple[ExtraInfo, Union[Awaitable[ChatCompletion], Awaitable[AsyncStream[ChatCompletionChunk]]]]:
        use_agentic_retrieval = True if overrides.get("use_agentic_retrieval") else False
        original_user_query = messages[-1]["content"]

        reasoning_model_support = self.GPT_REASONING_MODELS.get(self.chatgpt_model)
        if reasoning_model_support and (not reasoning_model_support.streaming and should_stream):
            raise Exception(
                f"{self.chatgpt_model} does not support streaming. Please use a different model or disable streaming."
            )
        if use_agentic_retrieval:
            extra_info = await self.run_agentic_retrieval_approach(messages, overrides, auth_claims)
        else:
            extra_info = await self.run_search_approach(messages, overrides, auth_claims)

        messages = self.prompt_manager.render_prompt(
            self.answer_prompt,
            self.get_system_prompt_variables(overrides.get("prompt_template"))
            | {
                "include_follow_up_questions": bool(overrides.get("suggest_followup_questions")),
                "past_messages": messages[:-1],
                "user_query": original_user_query,
                "text_sources": extra_info.data_points.text,
            },
        )

        chat_coroutine = cast(
            Union[Awaitable[ChatCompletion], Awaitable[AsyncStream[ChatCompletionChunk]]],
            self.create_chat_completion(
                self.chatgpt_deployment,
                self.chatgpt_model,
                messages,
                overrides,
                self.get_response_token_limit(self.chatgpt_model, 1024),
                should_stream,
            ),
        )
        extra_info.thoughts.append(
            self.format_thought_step_for_chatcompletion(
                title="Prompt to generate answer",
                messages=messages,
                overrides=overrides,
                model=self.chatgpt_model,
                deployment=self.chatgpt_deployment,
                usage=None,
            )
        )
        return (extra_info, chat_coroutine)

    async def run_search_approach(
        self, messages: list[ChatCompletionMessageParam], overrides: dict[str, Any], auth_claims: dict[str, Any]
    ):
        use_text_search = overrides.get("retrieval_mode") in ["text", "hybrid", None]
        use_vector_search = overrides.get("retrieval_mode") in ["vectors", "hybrid", None]
        use_semantic_ranker = True if overrides.get("semantic_ranker") else False
        use_semantic_captions = True if overrides.get("semantic_captions") else False
        use_query_rewriting = True if overrides.get("query_rewriting") else False
        top = overrides.get("top", 3)
        minimum_search_score = overrides.get("minimum_search_score", 0.0)
        minimum_reranker_score = overrides.get("minimum_reranker_score", 0.0)
        search_index_filter = self.build_filter(overrides, auth_claims)

        original_user_query = messages[-1]["content"]
        if not isinstance(original_user_query, str):
            raise ValueError("The most recent message content must be a string.")

        query_messages = self.prompt_manager.render_prompt(
            self.query_rewrite_prompt, {"user_query": original_user_query, "past_messages": messages[:-1]}
        )
        tools: list[ChatCompletionToolParam] = self.query_rewrite_tools

        # STEP 1: Generate an optimized keyword search query based on the chat history and the last question

        chat_completion = cast(
            ChatCompletion,
            await self.create_chat_completion(
                self.chatgpt_deployment,
                self.chatgpt_model,
                messages=query_messages,
                overrides=overrides,
                response_token_limit=self.get_response_token_limit(
                    self.chatgpt_model, 100
                ),  # Setting too low risks malformed JSON, setting too high may affect performance
                temperature=0.0,  # Minimize creativity for search query generation
                tools=tools,
                reasoning_effort="low",  # Minimize reasoning for search query generation
            ),
        )

        query_text = self.get_search_query(chat_completion, original_user_query)

        # STEP 2: Retrieve relevant documents from the search index with the GPT optimized query

        # If retrieval mode includes vectors, compute an embedding for the query
        vectors: list[VectorQuery] = []
        if use_vector_search:
            vectors.append(await self.compute_text_embedding(query_text))

        results = await self.search(
            top,
            query_text,
            search_index_filter,
            vectors,
            use_text_search,
            use_vector_search,
            use_semantic_ranker,
            use_semantic_captions,
            minimum_search_score,
            minimum_reranker_score,
            use_query_rewriting,
        )

        # STEP 3: Generate a contextual and content specific answer using the search results and chat history
        text_sources = self.get_sources_content(results, use_semantic_captions, use_image_citation=False)
        
        # Process sensitivity labels from search results
        try:
            sensitivity_info = await self._process_sensitivity_labels(results, auth_claims)
            print(f"SENSITIVITY PROCESSING COMPLETED: {sensitivity_info}")
        except Exception as e:
            print(f"ERROR in sensitivity processing: {e}")
            sensitivity_info = None

        extra_info = ExtraInfo(
            data_points=DataPoints(text=text_sources),
            sensitivity=sensitivity_info,
            thoughts=[
                self.format_thought_step_for_chatcompletion(
                    title="Prompt to generate search query",
                    messages=query_messages,
                    overrides=overrides,
                    model=self.chatgpt_model,
                    deployment=self.chatgpt_deployment,
                    usage=chat_completion.usage,
                    reasoning_effort="low",
                ),
                ThoughtStep(
                    "Search using generated search query",
                    query_text,
                    {
                        "use_semantic_captions": use_semantic_captions,
                        "use_semantic_ranker": use_semantic_ranker,
                        "use_query_rewriting": use_query_rewriting,
                        "top": top,
                        "filter": search_index_filter,
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
        return extra_info

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
            messages=messages,
            agent_client=self.agent_client,
            search_index_name=self.search_index_name,
            top=top,
            filter_add_on=search_index_filter,
            minimum_reranker_score=minimum_reranker_score,
            max_docs_for_reranker=max_docs_for_reranker,
            results_merge_strategy=results_merge_strategy,
        )

        text_sources = self.get_sources_content(results, use_semantic_captions=False, use_image_citation=False)
        
        # Process sensitivity labels from search results
        try:
            sensitivity_info = await self._process_sensitivity_labels(results, auth_claims)
            print(f"AGENTIC: SENSITIVITY PROCESSING COMPLETED: {sensitivity_info}")
        except Exception as e:
            print(f"AGENTIC: ERROR in sensitivity processing: {e}")
            sensitivity_info = None

        extra_info = ExtraInfo(
            data_points=DataPoints(text=text_sources),
            sensitivity=sensitivity_info,
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
            
            # Extract user's Graph access token for delegated inheritance computation
            user_graph_token = auth_claims.get("graph_access_token")

            
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
            
            # Extract document labels using the label helper
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
            import logging
            logging.getLogger(__name__).warning(f"Failed to process sensitivity labels: {e}")
            return None
