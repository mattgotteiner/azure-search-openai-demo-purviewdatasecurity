"""
Sensitivity Label Helper for Microsoft Purview Integration
Handles extraction, inheritance, and display of sensitivity labels from search results.
"""

import logging
import uuid
import os
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class SensitivityLabel:
    """Represents a sensitivity label with metadata"""
    id: str
    name: str
    display_name: str
    color: str = "gray"
    priority: int = 0
    
    
@dataclass  
class DocumentLabel:
    """Label information for a specific document"""
    document_id: str
    source_file: str
    label: SensitivityLabel


@dataclass
class ResponseSensitivity:
    """Overall response sensitivity computed from document labels"""
    overall_label: SensitivityLabel
    document_labels: list[DocumentLabel]


class LabelHelper:
    """Helper class for processing sensitivity labels from search results"""
    
    def __init__(self):
        """Initialize the label helper."""
        # Check environment variables for Graph API features
        self.enable_graph_label_resolution = os.getenv("ENABLE_GRAPH_LABEL_RESOLUTION", "true").lower() == "true"
        
    async def _get_credential(self):
        """Get Azure credential for API calls"""
        # Import here to avoid circular imports
        from azure.identity.aio import AzureDeveloperCliCredential, ManagedIdentityCredential
        
        # Check if running on Azure (same logic as app.py)
        RUNNING_ON_AZURE = os.getenv("WEBSITE_HOSTNAME") is not None or os.getenv("RUNNING_IN_PRODUCTION") is not None
        AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID")
        AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
        
        if RUNNING_ON_AZURE:
            if AZURE_CLIENT_ID:
                return ManagedIdentityCredential(client_id=AZURE_CLIENT_ID)
            else:
                return ManagedIdentityCredential()
        elif AZURE_TENANT_ID:
            return AzureDeveloperCliCredential(tenant_id=AZURE_TENANT_ID, process_timeout=60)
        else:
            return AzureDeveloperCliCredential(process_timeout=60)
        
    async def _resolve_purview_label(self, label_id: str, user_access_token: Optional[str] = None) -> Optional[SensitivityLabel]:
        """
        Resolve a Purview label GUID to a SensitivityLabel using Microsoft Graph API.
        
        Args:
            label_id: The GUID of the Purview label
            user_access_token: Optional user access token for delegated permissions
            
        Returns:
            SensitivityLabel or None if resolution fails
        """
        try:
            # Use user token if provided (delegated permissions), otherwise fall back to app credentials
            if user_access_token:
                access_token = user_access_token
                # Remove 'Bearer ' prefix if present
                if access_token.startswith('Bearer '):
                    access_token = access_token[7:]
            else:
                credential = await self._get_credential()
                if not credential:
                    logger.warning("No credential available for Graph API call")
                    return None
                    
                token = await credential.get_token("https://graph.microsoft.com/.default")
                access_token = token.token
            
            # Try to get label details from Microsoft Graph API
            graph_base_url = "https://graph.microsoft.com/v1.0"
            url = f"{graph_base_url}/security/dataSecurityAndGovernance/sensitivityLabels/{label_id}"
            
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                    "User-Agent": "Purview-Python-Client"
                }
                
                async with session.get(url, headers=headers, timeout=10.0) as response:
                    if response.status == 200:
                        label_data = await response.json()
                        
                        # Extract label information
                        label_name = label_data.get('name', f'Label-{label_id[:8]}')
                        raw_display_name = label_data.get('displayName')
                        display_name = raw_display_name if raw_display_name else label_name
                        
                        # Get actual color from API response
                        api_color = label_data.get('color', '#808080')  # Default to gray if no color
                        
                        # Get priority from API response
                        priority = label_data.get('priority', 0)
                        
                        # Create the SensitivityLabel object
                        resolved_label = SensitivityLabel(
                            id=label_id,
                            name=label_name,
                            display_name=display_name,
                            color=api_color,
                            priority=priority
                        )
                        
                        return resolved_label
                    else:
                        error_text = await response.text()
                        logger.error(f"Graph API label resolution failed for {label_id}: Status {response.status}, Error: {error_text}")
                        return None
                        
        except Exception as e:
            logger.error(f"Exception during Graph API label resolution for {label_id}: {str(e)}")
            return None
        
    async def extract_labels_from_search_results(self, search_results: List[Dict[str, Any]], user_access_token: Optional[str] = None) -> List[DocumentLabel]:
        """Extract sensitivity labels from search results"""
        document_labels = []
        
        for i, result in enumerate(search_results):
            doc_id = result.get("id", f"unknown_{i}")
            # Try multiple potential source file field names
            source_file = (
                result.get("sourcefile") or 
                result.get("source_file") or 
                result.get("metadata_storage_name") or 
                "unknown"
            )
            
            # Check the actual indexer field first
            metadata_sensitivity_label = result.get("metadata_sensitivity_label")
            
            effective_label = metadata_sensitivity_label
            
            label = None
            
            # First try to get label from the indexer metadata
            if effective_label:
                # Check if it's a GUID (potential Purview label ID)
                if self._is_guid(effective_label) and self.enable_graph_label_resolution:
                    label = await self._resolve_purview_label(effective_label, user_access_token)
                    if not label:
                        # Create fallback GUID label if resolution failed
                        label = SensitivityLabel(
                            id=effective_label,
                            name=f"Purview Label ({effective_label[:8]}...)",
                            display_name=f"Purview Label (ID: {effective_label[:8]}...)",
                            color="orange",
                            priority=0
                        )
                
                # If not resolved yet, try to create from string
                if not label:
                    label = self._create_label_from_string(effective_label)
            
            if label:
                document_labels.append(DocumentLabel(
                    document_id=doc_id,
                    source_file=source_file,
                    label=label
                ))
        
        return document_labels

    def _is_guid(self, value: str) -> bool:
        """Check if a string is a valid GUID"""
        try:
            uuid.UUID(value)
            return True
        except ValueError:
            return False

    def _create_label_from_string(self, label_name: str) -> SensitivityLabel:
        """Create a SensitivityLabel from a label name string - preserving exact name"""
        return SensitivityLabel(
            id=label_name.lower().replace(" ", "-"),
            name=label_name,
            display_name=label_name,
            color="orange",
            priority=0
        )
            
    async def compute_label_inheritance(self, document_labels: list[DocumentLabel], user_access_token: Optional[str] = None) -> ResponseSensitivity:
        """
        Compute the overall sensitivity label for a response based on document labels.
        Uses priority from resolved labels, or picks first document if no priority available.
        
        Args:
            document_labels: List of DocumentLabel objects
            user_access_token: Optional user access token (unused but kept for compatibility)
            
        Returns:
            ResponseSensitivity with overall label, or None if no documents
        """
        if not document_labels:
            # No labels found - return None to display nothing
            return None
        
        # Check if any labels have priority values
        labels_with_priority = [dl for dl in document_labels if dl.label.priority > 0]
        
        if labels_with_priority:
            # Sort by priority (higher is more sensitive)
            sorted_labels = sorted(labels_with_priority, key=lambda dl: dl.label.priority, reverse=True)
            chosen_label = sorted_labels[0].label
        else:
            # No priority available, just use the first document's label
            chosen_label = document_labels[0].label
        
        return ResponseSensitivity(
            overall_label=chosen_label,
            document_labels=document_labels
        )

    def get_sensitivity_badge_info(self, label: SensitivityLabel) -> dict[str, any]:
        """Get badge information for displaying sensitivity labels"""
        return {
            "text": label.display_name,
            "color": label.color,
            "priority": label.priority,
            "id": label.id,
            "icon": "🔒"
        }
