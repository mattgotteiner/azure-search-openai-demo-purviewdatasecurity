export interface ProtectionScopeResult {
    scopeIdentifier: string;
    etag: string;
    notModified: boolean;
}

export async function getProtectionScope(accessToken: string, userId: string, previousEtag?: string): Promise<ProtectionScopeResult> {
    const url = `https://graph.microsoft.com/v1.0/me/dataSecurityAndGovernance/protectionScopes/compute`;

    const headers: Record<string, string> = {
        Authorization: `Bearer ${accessToken}`,
        "Content-Type": "application/json"
    };

    if (previousEtag) {
        headers["If-None-Match"] = previousEtag;
    }

    const response = await fetch(url, {
        method: "POST",
        headers,
        body: JSON.stringify({ dataType: "text" })
    });

    if (response.status === 304) {
        return {
            scopeIdentifier: "",
            etag: previousEtag || "",
            notModified: true
        };
    }

    if (!response.ok) {
        const error = await response.json();
        throw new Error(`Protection scope error: ${JSON.stringify(error)}`);
    }

    const responseBody = await response.json();
    const etag = response.headers.get("ETag") || "";
    const activityModes: Record<string, string> = {};

    for (const item of responseBody.value) {
        const activities = item.activities.split(",");
        const mode = item.executionMode;

        for (const activity of activities) {
            const trimmed = activity.trim();
            const existingMode = activityModes[trimmed];

            if (!existingMode || (existingMode === "evaluateOffline" && mode === "evaluateInline")) {
                activityModes[trimmed] = mode;
            }
        }
    }

    for (const [activity, mode] of Object.entries(activityModes)) {
        sessionStorage.setItem(activity, mode);
    }

    return {
        scopeIdentifier: responseBody.scopeIdentifier,
        etag,
        notModified: false
    };
}
