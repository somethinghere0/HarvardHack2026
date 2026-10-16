# Proposed proxy API (sketch, not implemented)

POST /auth/signup   {username, password, first_name, last_name, address{street_number,street_name,city,state,zip}}
                    -> 201 {token, expires_at, customer_id}    | 409 username taken | 422 weak/invalid input
POST /auth/login    {username, password} -> 200 {token, expires_at} | 401 | 429 (Retry-After)
POST /auth/logout   Authorization: Bearer <session token> -> 204
GET  /auth/me       Authorization: Bearer <session token> -> 200 {username, customer_id}
GET  /health        public -> 200

ANY  /<nessie path> Authorization: Bearer <session token>
                    -> forwarded to NESSIE_BASE_URL with the server-held Nessie key
                    (client Authorization header is stripped, never forwarded)

# Environment
NESSIE_API_KEY=nsk_...            # required, never sent to clients
NESSIE_BASE_URL=https://v2-prod-api.nessieisreal.com
SESSION_TTL_HOURS=12
DB_PATH=/data/proxy.db            # docker volume
# Source for the Nessie shapes: openapi.yaml (CustomerCreateDTO, bearerAuth, servers)
