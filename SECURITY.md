# Security policy

Do not commit Telegram tokens, API keys, SSH keys, passwords, internal host
addresses, production environment files, model weights, or raw user content.
Tracked `*.env.example` files contain placeholders and safe defaults only.

The llama.cpp RPC protocol is unauthenticated. Bind it only to a trusted private
point-to-point network and firewall it from untrusted networks.
