import { config } from "./config";

export async function processContent(
    accessToken: string,
    userId: string,
    message: string,
    messageType: "prompt" | "response",
    conversationId: string,
    sequenceNumber: number,
    scopeIdentifier: string
): Promise<Response> {
    const processContentPayload = {
        contentToProcess: {
            contentEntries: [
                {
                    "@odata.type": "#microsoft.graph.processConversationMetadata",
                    identifier: conversationId,
                    content: {
                        "@odata.type": "#microsoft.graph.textContent",
                        data: message
                    },
                    name: `Chat-${conversationId}.txt`,
                    correlationId: conversationId,
                    sequenceNumber: sequenceNumber,
                    createdDateTime: new Date().toISOString(),
                    modifiedDateTime: new Date().toISOString()
                }
            ],
            activityMetadata: {
                activity: messageType === "response" ? "downloadText" : "uploadText"
            },
            deviceMetadata: {
                operatingSystemSpecifications: {
                    operatingSystemPlatform: "Windows",
                    operatingSystemVersion: "10.0.19045"
                }
            },
            protectedAppMetadata: {
                name: "PC Purview Workload",
                version: "0.2",
                applicationLocation: {
                    "@odata.type": "microsoft.graph.policyLocationApplication",
                    value: config.CLIENT_ID
                }
            },
            integratedAppMetadata: {
                name: "PCA Workload Sample - IA",
                version: "1.0"
            }
        }
    };

    const processContentUrl = `https://graph.microsoft.com/beta/me/dataSecurityAndGovernance/processContent`;

    const headers = {
        Authorization: `Bearer ${accessToken}`,
        "User-Agent": "Purview API Explorer",
        "client-request-id": "1ff21074-ab16-41e7-a445-f002f8a778ae",
        "x-ms-client-request-id": "c21508b6-41c4-4074-9f6e-fe898476d739",
        "Content-Type": "application/json"
    };

    const processResponse = await fetch(processContentUrl, {
        method: "POST",
        headers: headers,
        body: JSON.stringify(processContentPayload)
    });

    const p4aiJson = await processResponse.json();
    sessionStorage.setItem("scopeState", p4aiJson.protectionScopeState);
    if (p4aiJson.policyActions && p4aiJson.policyActions.length > 0) {
        const action = p4aiJson.policyActions[0].action;
        if (action === "restrictAccess" || action === "blockAccess") {
            const error = new Error("Blocked by policy");
            (error as any).code = "PURVIEW_POLICY_BLOCK";
            throw error;
        }
    }

    return processResponse;
}
