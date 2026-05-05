# Insighta Labs+ Backend

## 1. System Architecture

Three repositories:

- Backend: Python FastAPI, deployed on Vercel
- CLI: Node.js, runs locally
- Web Portal: React/Vite, deployed on Vercel

All interfaces share one backend and one Supabase database.

## 2. Authentication Flow

### CLI Flow (PKCE):

1. CLI generates `state` and `code_verifier` locally
2. CLI starts local server on localhost:3000
3. CLI opens browser → backend `/auth/github?state=X&code_verifier=Y`
4. Backend stores state + code_verifier in `auth_state` table
5. Backend redirects to GitHub OAuth
6. GitHub redirects to backend `/auth/github/callback`
7. Backend validates state, looks up code_verifier
8. Backend exchanges code with GitHub
9. Backend creates/updates user in `users` table
10. Backend issues JWT access token (3min) + refresh token (5min)
11. Backend redirects to localhost:3000 with tokens in URL
12. CLI saves tokens to ~/.insighta/credentials.json

### Web Flow:

1. User clicks "Continue with GitHub"
2. Browser redirects to backend `/auth/github?state=X`
3. Same flow as CLI except no code_verifier
4. Backend sets HttpOnly cookies instead of redirecting with tokens
5. User lands on dashboard

## 3. CLI Usage

```bash
# Auth
node index.js login
node index.js logout
node index.js whoami

# Profiles
node index.js profiles list
node index.js profiles list --gender male
node index.js profiles list --country NG --age-group adult
node index.js profiles list --min-age 25 --max-age 40
node index.js profiles list --sort-by age --order desc
node index.js profiles list --page 2 --limit 20
node index.js profiles get <id>
node index.js profiles search "young males from nigeria"
node index.js profiles create --name "Harriet Tubman"
node index.js profiles export --format csv
node index.js profiles export --format csv --gender male --country NG
```

## 4. Token Handling

- Access token: JWT, expires in exactly 3 minutes
- Refresh token: JWT, expires in exactly 5 minutes
- Token rotation: each refresh invalidates old pair, issues new pair
- CLI: auto-refreshes on 401, prompts re-login if refresh fails
- Web: cookies expire with tokens, user redirected to login

## 5. Role Enforcement

Two roles: `admin` and `analyst`. Default: `analyst`.

Enforced via `require_role()` dependency in FastAPI:

- `analyst`: can read and search profiles
- `admin`: can create, delete, export profiles

Every `/api/*` request goes through `get_current_user()` which:

1. Reads token from Authorization header or cookie
2. Decodes JWT using JWT_SECRET
3. Looks up user in Supabase users table
4. Checks `is_active` flag — returns 403 if false
5. Returns user object to route handler

## 6. Natural Language Parsing

The `extract_filters()` function in `routers/profiles.py` parses
plain English queries into database filters:

- Gender: "male/men" → gender=male, "female/women" → gender=female
- Age: "young" → age 16-24, "teenager/adult/senior/child" → age_group
- Numbers: "over 30" → min_age=30, "under 25" → max_age=25
- Countries: "nigeria" → NG, "kenya" → KE, "ghana" → GH etc

Example: "young males from nigeria" →
gender=male, min_age=16, max_age=24, country_id=NG
