export var apitoken: string;

export function setApiToken(token: string) {
    apitoken = token;
}

export function getApiToken(): string {
    if (!apitoken) {
        throw new Error("API token is not set.");
    }
    return apitoken;
}

export async function getUserIdFromToken(accessToken: string): Promise<string | null> {
    try {
        const payloadBase64 = accessToken.split(".")[1];
        if (!payloadBase64) return null;

        const payloadJson = atob(payloadBase64.replace(/-/g, "+").replace(/_/g, "/"));

        const payload = JSON.parse(payloadJson);

        return payload.oid ?? payload.sub ?? null;
    } catch (error) {
        console.error("Error decoding token:", error);
        return null;
    }
}
