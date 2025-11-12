# Purview Authentication Setup

This document explains how to ensure the backend generates tokens that work with the Purview frontend code.

## Overview

The application now uses a unified authentication mechanism where the original MSAL authentication provides tokens that work for both:
1. Backend API calls (using `api://{server_app_id}/access_as_user`)
2. Microsoft Purview API calls (using Microsoft Graph Purview scopes)

## Required Microsoft Graph Purview Scopes

The following scope is required for Purview data security and governance functionality:

1. **ProtectionScopes.Compute.User** (UUID: `4fc04d16-a9fc-4c5e-8da4-79b6c33638a4`) - This delegated permission allows the app to identify Purview data protection, compliance and governance policy scopes defined for an individual user. This permission provides access to:
   - Computing protection scopes (`/me/dataSecurityAndGovernance/protectionScopes/compute`)

2. **Content.Process.User** (UUID: `1d787a13-f750-4ad6-875a-fcbd2725596b`) - This delegated permission allows the app to process and evaluate content for data security, governance, and compliance outcomes for a user. This permission provides access to:
   - Processing content through Purview DLP policies (`/me/dataSecurityAndGovernance/processContent`)
   - Writing content activity logs for audit and compliance

Both permissions are required for the complete Purview integration.

## Setup Steps

### 1. Run Authentication Initialization

The `auth_init.py` script has been updated with the correct Microsoft Graph permission UUID for `Content.Process.User`.

After updating the UUIDs, run:

```bash
python scripts/auth_init.py
```

This will:
- Create/update the server app registration with Purview permissions
- Create/update the client app registration with Purview permissions
- Generate client secrets if needed

### 2. Grant Admin Consent

After running auth_init.py, you need to grant admin consent for the Purview permissions:

1. Go to Azure Portal → Microsoft Entra ID → App registrations
2. Find your "Azure Search OpenAI Chat Client App"
3. Go to "API permissions"
4. Click "Grant admin consent for [Your Tenant]"

This is required because Purview scopes typically require admin consent.

### 5. Verify Configuration

The backend configuration in `app/backend/core/authentication.py` should include:

```python
"tokenRequest": {
    "scopes": [f"api://{self.server_app_id}/access_as_user"],
}
```

The frontend configuration in `app/frontend/src/authConfig.ts` includes a separate `getGraphToken()` function that requests:

```typescript
const graphTokenRequest = {
    scopes: [
        "https://graph.microsoft.com/Content.Process.User",
        "https://graph.microsoft.com/User.Read"
    ]
};
```

## How It Works

The authentication system uses **two separate tokens** because JWT tokens can only have one audience:

1. **User logs in** via the LoginButton component using MSAL
2. **Two tokens are acquired**:
   - **Backend API Token**: Audience = `api://{server_app_id}`, Scope = `access_as_user`
   - **Graph API Token**: Audience = `https://graph.microsoft.com`, Scopes = Purview permissions
3. **Tokens are used for different purposes**:
   - Backend API token → Backend API calls
   - Graph API token → Purview API calls (via Microsoft Graph)

## Token Flow

```
┌─────────────┐
│   Frontend  │
│   (MSAL)    │
└──────┬──────┘
       │ Login
       │
       ▼
┌─────────────────┐
│   Azure AD      │
└──────┬──────────┘
       │
       ├──────────────────────────┐
       │                          │
       │ getToken()               │ getGraphToken()
       │ (backend API)            │ (Graph/Purview)
       │                          │
       ▼                          ▼
┌──────────────────┐      ┌──────────────────┐
│ Backend API Token│      │ Graph API Token  │
│ Audience:        │      │ Audience:        │
│ api://app-id     │      │ graph.ms.com     │
└────────┬─────────┘      └────────┬─────────┘
         │                         │
         ▼                         ▼
  ┌────────────┐          ┌──────────────┐
  │  Backend   │          │   Purview    │
  │  API       │          │   APIs       │
  └────────────┘          └──────────────┘
```

## Troubleshooting

### Token doesn't have Purview scopes

**Problem**: Token acquired by frontend doesn't include Purview scopes

**Solutions**:
1. Verify scopes are correctly configured in `authentication.py`
2. Check that admin consent was granted in Azure Portal
3. Clear browser cache and session storage
4. Try logging out and back in to acquire a new token

### Purview API returns 403 Forbidden

**Problem**: Purview APIs reject the token

**Solutions**:
1. Verify the app registration includes the Purview permissions
2. Check that admin consent was granted
3. Verify the user has Purview licenses assigned
4. Check that the tenant has Purview enabled

### "Invalid audience" error

**Problem**: Token audience doesn't match what Purview expects

**Solutions**:
1. Ensure you're requesting scopes with the full URL format:
   - ✅ `https://graph.microsoft.com/Content.Process.User`
   - ❌ `Content.Process.User`
2. Check that the token is being sent to the correct endpoint

## Environment Variables

Make sure these are set (automatically set by `azd` and `auth_init.py`):

```bash
AZURE_SERVER_APP_ID=<server-app-id>
AZURE_SERVER_APP_SECRET=<server-app-secret>
AZURE_CLIENT_APP_ID=<client-app-id>
AZURE_AUTH_TENANT_ID=<tenant-id>
```

## Testing

To verify both tokens are working correctly:

```javascript
// In browser console after login
import { getToken, getGraphToken } from './authConfig';

// Get backend API token
const backendToken = await getToken(client);
console.log('Backend Token:', backendToken);
// Decode at jwt.ms - should show audience: api://{your-app-id}

// Get Graph API token  
const graphToken = await getGraphToken(client);
console.log('Graph Token:', graphToken);
// Decode at jwt.ms - should show audience: https://graph.microsoft.com
// and the Purview scopes in the 'scp' claim
```

The decoded Graph token should show:
- **Audience (`aud`)**: `https://graph.microsoft.com` or `00000003-0000-0000-c000-000000000000`
- **Scopes (`scp`)**: Should include `Content.Process.User` and `User.Read`
