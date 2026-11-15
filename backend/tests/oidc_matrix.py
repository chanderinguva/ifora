"""IFORA-24: the OIDC/OAuth conformance matrix as data.

Each row ties a clause of a specification to the tests that prove it. `test_oidc_conformance.py` checks that every
referenced test exists and that the discovery document advertises nothing that has no row. `scripts/oidc_matrix.py`
runs the referenced tests and writes the matrix with their real results, so the document is output, not a claim.

A test reference is "<file>::<test name>" relative to backend/tests. Status "supported" rows need at least one test;
"not-supported" rows document what is deliberately absent (and must not be advertised).
"""

from typing import Dict, List, NamedTuple, Tuple


class Row(NamedTuple):
    id: str
    spec: str
    clause: str
    requirement: str
    tests: Tuple[str, ...]
    status: str = "supported"


A = "adversarial/test_oidc_attacks.py::"
TOK = "test_oidc_token.py::"
AZ = "test_oidc_authorize.py::"
RF = "test_oidc_refresh.py::"
KY = "test_oidc_keys.py::"
PK = "test_oidc_pkjwt_es256.py::"
SC = "test_oidc_service_clients.py::"
OP = "test_oidc_opaque.py::"
LG = "test_oidc_prompts_logout.py::"
HD = "test_oidc_hardening.py::"
CN = "test_oidc_conformance.py::"

ROWS: List[Row] = [
    # OpenID Connect Core 1.0
    Row("CORE-3.1.2.1", "OIDC Core", "3.1.2.1", "Authorization request: response_type=code, scope contains openid",
        (AZ + "test_validation_errors_redirect_with_state_and_iss", AZ + "test_untrusted_client_or_redirect_is_shown_never_redirected")),
    Row("CORE-3.1.2.3", "OIDC Core", "3.1.2.3", "Authentication: sign in when no session; prompt=none returns login_required without UI",
        (AZ + "test_anonymous_parks_request_and_redirects_to_ui", AZ + "test_prompt_none_without_session_is_login_required")),
    Row("CORE-3.1.2.1-prompt", "OIDC Core", "3.1.2.1", "prompt (none, login, consent, select_account) and max_age",
        (LG + "test_prompt_login_forces_a_fresh_sign_in_even_for_first_party", LG + "test_max_age_within_limit_is_sso_and_beyond_it_reauthenticates",
         AZ + "test_prompt_consent_forces_screen_prompt_none_fails_when_consent_needed")),
    Row("CORE-3.1.2.4", "OIDC Core", "3.1.2.4", "Consent: required for third parties, remembered, revocable",
        (AZ + "test_third_party_needs_consent_then_code", AZ + "test_wider_scopes_need_fresh_consent", AZ + "test_revoked_consent_requires_consent_again")),
    Row("CORE-3.1.2.5", "OIDC Core", "3.1.2.5", "Successful response: code and state; error responses carry state and iss",
        (AZ + "test_validation_errors_redirect_with_state_and_iss", A + "test_state_is_echoed_verbatim_and_cannot_inject_headers_or_parameters")),
    Row("CORE-3.1.3.1", "OIDC Core", "3.1.3.1", "Token request: code exchange, redirect_uri must match, code single use",
        (TOK + "test_public_client_code_exchange_issues_id_and_access_tokens", TOK + "test_redirect_uri_must_match_exactly", TOK + "test_code_is_single_use_and_replay_is_audited")),
    Row("CORE-3.1.3.7", "OIDC Core", "3.1.3.7", "ID Token validation inputs: iss, aud, exp, iat, nonce, at_hash, auth_time, amr, acr",
        (TOK + "test_public_client_code_exchange_issues_id_and_access_tokens", A + "test_nonce_is_bound_into_the_id_token_unchanged", LG + "test_id_token_carries_auth_time_of_the_fresh_login")),
    Row("CORE-5.1", "OIDC Core", "5.1", "Standard claims returned by scope (profile, email, groups); userinfo bearer only",
        (TOK + "test_userinfo_returns_scoped_claims", TOK + "test_groups_claim_only_with_groups_scope", TOK + "test_userinfo_rejects_bad_tokens")),
    Row("CORE-9", "OIDC Core", "9", "Client authentication: client_secret_basic, private_key_jwt (RS256, ES256), none for public clients",
        (TOK + "test_confidential_client_with_basic_auth", PK + "test_authorization_code_exchange_with_an_es256_assertion", PK + "test_rs256_assertion_and_issuer_as_audience", TOK + "test_public_client_cannot_present_a_secret_and_unknown_clients_fail")),
    Row("CORE-11", "OIDC Core", "11", "offline_access issues a refresh token; clients without it cannot ask",
        (RF + "test_refresh_token_only_with_offline_access", RF + "test_client_without_offline_access_scope_cannot_ask")),
    Row("CORE-15.1", "OIDC Core", "15.1", "Signing: RS256 and ES256 published; alg none and HS256 confusion refused",
        (KY + "test_signed_token_has_kid_alg_typ_and_validates", KY + "test_alg_none_and_hs256_confusion_rejected", PK + "test_es256_keys_sign_and_verify_and_coexist_with_rs256")),
    Row("CORE-claims-param", "OIDC Core", "5.5/6", "claims, request and request_uri parameters are not supported and not advertised",
        (CN + "test_unsupported_features_are_not_advertised",), "not-supported"),
    # OIDC Discovery 1.0 / RFC 8414
    Row("DISC-3", "OIDC Discovery", "3/4", "Provider metadata document with issuer, endpoints, supported values",
        (CN + "test_every_advertised_feature_has_a_matrix_row", CN + "test_discovery_matches_the_issuer_that_served_it")),
    Row("RFC8414-2", "RFC 8414", "2", "Metadata includes revocation and introspection endpoints with their auth methods",
        (CN + "test_every_advertised_feature_has_a_matrix_row", LG + "test_discovery_advertises_logout_and_prompts", SC + "test_discovery_lists_the_grant_and_introspection")),
    Row("JWKS", "RFC 7517/7518", "-", "jwks_uri publishes public keys only, cacheable; rotation publishes before use and overlaps after",
        (KY + "test_jwks_endpoint_is_public_cacheable_and_leaks_no_private_material", KY + "test_rotation_publishes_new_key_before_it_signs", KY + "test_rotation_overlap_old_tokens_verify_then_stop", KY + "test_keys_are_per_tenant")),
    # RFC 6749 and friends
    Row("RFC6749-4.1", "RFC 6749", "4.1", "Authorization code grant; error codes invalid_request, invalid_grant, invalid_client, unauthorized_client",
        (TOK + "test_missing_or_malformed_parameters", TOK + "test_wrong_verifier_fails_and_burns_the_code", TOK + "test_confidential_client_needs_its_secret", A + "test_code_cannot_be_redeemed_by_another_client")),
    Row("RFC6749-4.4", "RFC 6749", "4.4", "Client credentials grant for service clients only",
        (SC + "test_client_credentials_issues_an_access_token_only", SC + "test_other_client_types_cannot_use_the_grant", SC + "test_service_client_cannot_run_user_flows")),
    Row("RFC6749-6", "RFC 6749", "6", "Refresh: rotation, scope may narrow never widen, idle and absolute expiry",
        (RF + "test_refresh_rotates_and_returns_fresh_tokens", RF + "test_scope_can_be_narrowed_never_widened", RF + "test_idle_and_absolute_expiry")),
    Row("RFC6749-10.4", "RFC 6749 / BCP", "10.4", "Refresh token reuse revokes the family (rotation with reuse detection)",
        (RF + "test_reusing_a_rotated_token_revokes_the_whole_family", A + "test_a_rotated_refresh_token_presented_again_revokes_the_whole_family")),
    Row("RFC6749-5.2", "RFC 6749", "3.2", "Token endpoint: POST, form encoded, secrets never in the body, rate limited",
        (TOK + "test_only_authorization_code_grant_and_form_encoding", TOK + "test_secret_in_body_is_refused", TOK + "test_failures_are_rate_limited")),
    Row("RFC7636", "RFC 7636 (PKCE)", "4", "S256 is mandatory; plain and missing challenges refused; wrong verifier burns the code",
        (A + "test_pkce_downgrade_attempts_never_issue_a_code", A + "test_wrong_or_missing_code_verifier_gets_invalid_grant_and_no_token", A + "test_a_failed_verifier_burns_the_code_so_it_cannot_be_guessed_at")),
    Row("RFC7009", "RFC 7009", "2", "Revocation: a refresh token revokes its family; opaque access tokens at once; clients revoke only their own",
        (OP + "test_user_opaque_token_userinfo_introspection_and_revocation", RF + "test_withdrawing_consent_kills_refresh_tokens", PK + "test_introspection_and_revocation_accept_assertions")),
    Row("RFC7662", "RFC 7662", "2", "Introspection: confidential and service callers only; follows the user; refresh tokens introspectable",
        (SC + "test_introspection_requires_a_confidential_or_service_caller", SC + "test_user_access_token_introspection_follows_the_user", SC + "test_refresh_token_introspection")),
    Row("RFC7523", "RFC 7523", "3", "private_key_jwt assertions: audience, single use, algorithm confusion refused",
        (PK + "test_an_assertion_is_single_use", PK + "test_algorithm_confusion_is_refused", A + "test_client_assertion_attacks_are_all_refused")),
    Row("RFC9068", "RFC 9068", "2.2", "JWT access tokens: typ at+jwt, iss, aud, sub, client_id, scope, jti, iat, exp; opaque format optional",
        (TOK + "test_public_client_code_exchange_issues_id_and_access_tokens", OP + "test_default_clients_still_get_jwts", OP + "test_client_credentials_opaque_token")),
    Row("RFC9207", "RFC 9207", "2", "Authorization response carries iss; discovery says so",
        (AZ + "test_validation_errors_redirect_with_state_and_iss", CN + "test_every_advertised_feature_has_a_matrix_row")),
    Row("OIDC-RP-LOGOUT", "RP-Initiated Logout 1.0", "2", "end_session_endpoint: exact post-logout URI match, hint validated, user confirms",
        (LG + "test_logout_ends_session_and_redirects_to_registered_uri_with_state", LG + "test_unregistered_post_logout_uris_are_never_used", LG + "test_logout_requires_csrf_when_a_session_exists")),
    Row("LOGOUT-REFRESH", "RP-Initiated Logout / BCP", "-", "Logout ends that client's refresh tokens (IFORA-24, AC3); other clients untouched",
        (LG + "test_logout_revokes_that_clients_refresh_tokens", LG + "test_logout_leaves_another_clients_refresh_tokens_alone", LG + "test_logout_without_an_identified_client_revokes_no_refresh_tokens")),
    Row("SEC-REDIRECT", "OAuth 2.0 Security BCP", "4.1", "Exact redirect URI matching; unknown clients and URIs are never redirected to",
        (A + "test_redirect_uri_must_match_a_registered_value_exactly", AZ + "test_untrusted_client_or_redirect_is_shown_never_redirected", AZ + "test_repeated_parameters_are_rejected")),
    Row("SEC-ENTITLEMENT", "Assessment SEC-B-1", "-", "Tokens stop when the user is unassigned or the app disabled",
        (OP + "test_unassigned_user_cannot_refresh_and_family_is_revoked", A + "test_unassigned_user_cannot_keep_minting_tokens")),
    Row("INTEROP", "Independent client", "-", "authlib completes code+PKCE, validates the ID token and JWKS, calls userinfo, refreshes (reuse detection) and revokes over real HTTP",
        (CN + "test_an_independent_client_completes_the_whole_flow_over_http",)),
    # Deliberately not supported
    Row("X-DEVICE", "RFC 8628", "-", "Device authorization grant", (CN + "test_unsupported_features_are_not_advertised",), "not-supported"),
    Row("X-PAR", "RFC 9126", "-", "Pushed authorization requests", (CN + "test_unsupported_features_are_not_advertised",), "not-supported"),
    Row("X-DCR", "RFC 7591", "-", "Dynamic client registration", (CN + "test_unsupported_features_are_not_advertised",), "not-supported"),
    Row("X-DPOP", "RFC 9449", "-", "DPoP sender-constrained tokens", (CN + "test_unsupported_features_are_not_advertised",), "not-supported"),
    Row("X-CIBA", "OIDC CIBA", "-", "Client-initiated backchannel authentication", (CN + "test_unsupported_features_are_not_advertised",), "not-supported"),
    Row("X-EXCHANGE", "RFC 8693", "-", "Token exchange", (CN + "test_unsupported_features_are_not_advertised",), "not-supported"),
    Row("X-BACKCHANNEL-LOGOUT", "OIDC Back-Channel Logout", "-", "Back-channel and front-channel logout notifications", (CN + "test_unsupported_features_are_not_advertised",), "not-supported"),
]

# Every discovery metadata key and the matrix rows that cover it. A key not listed here fails the test, so a new
# advertised feature cannot ship without a row.
DISCOVERY_COVERAGE: Dict[str, Tuple[str, ...]] = {
    "issuer": ("DISC-3",),
    "authorization_endpoint": ("CORE-3.1.2.1", "RFC6749-4.1"),
    "token_endpoint": ("CORE-3.1.3.1", "RFC6749-4.1", "RFC6749-5.2"),
    "userinfo_endpoint": ("CORE-5.1",),
    "jwks_uri": ("JWKS",),
    "response_types_supported": ("CORE-3.1.2.1",),
    "response_modes_supported": ("CORE-3.1.2.5",),
    "grant_types_supported": ("RFC6749-4.1", "RFC6749-4.4", "RFC6749-6"),
    "subject_types_supported": ("CORE-5.1",),
    "id_token_signing_alg_values_supported": ("CORE-15.1",),
    "scopes_supported": ("CORE-5.1", "CORE-11"),
    "token_endpoint_auth_methods_supported": ("CORE-9",),
    "token_endpoint_auth_signing_alg_values_supported": ("CORE-9", "RFC7523"),
    "code_challenge_methods_supported": ("RFC7636",),
    "claims_supported": ("CORE-5.1", "CORE-3.1.3.7"),
    "authorization_response_iss_parameter_supported": ("RFC9207",),
    "revocation_endpoint": ("RFC7009",),
    "revocation_endpoint_auth_methods_supported": ("RFC7009",),
    "introspection_endpoint": ("RFC7662",),
    "introspection_endpoint_auth_methods_supported": ("RFC7662",),
    "end_session_endpoint": ("OIDC-RP-LOGOUT",),
    "prompt_values_supported": ("CORE-3.1.2.1-prompt",),
    "acr_values_supported": ("CORE-3.1.3.7",),
    "claims_parameter_supported": ("CORE-claims-param",),
    "request_parameter_supported": ("CORE-claims-param",),
    "request_uri_parameter_supported": ("CORE-claims-param",),
}

# Values of list-valued metadata that the matrix says are supported; anything else advertised fails the test.
SUPPORTED_VALUES: Dict[str, Tuple[str, ...]] = {
    "response_types_supported": ("code",),
    "response_modes_supported": ("query",),
    "grant_types_supported": ("authorization_code", "refresh_token", "client_credentials"),
    "token_endpoint_auth_methods_supported": ("client_secret_basic", "private_key_jwt", "none"),
    "token_endpoint_auth_signing_alg_values_supported": ("RS256", "ES256"),
    "code_challenge_methods_supported": ("S256",),
    "introspection_endpoint_auth_methods_supported": ("client_secret_basic", "private_key_jwt"),
    "revocation_endpoint_auth_methods_supported": ("client_secret_basic", "private_key_jwt", "none"),
    "subject_types_supported": ("public",),
}

# Metadata keys that, if they ever appear, mean a feature the matrix lists as not supported has been advertised.
UNSUPPORTED_KEYS = (
    "device_authorization_endpoint",
    "pushed_authorization_request_endpoint",
    "require_pushed_authorization_requests",
    "registration_endpoint",
    "dpop_signing_alg_values_supported",
    "backchannel_authentication_endpoint",
    "backchannel_logout_supported",
    "backchannel_logout_session_supported",
    "frontchannel_logout_supported",
    "frontchannel_logout_session_supported",
)
UNSUPPORTED_GRANTS = (
    "urn:ietf:params:oauth:grant-type:device_code",
    "urn:ietf:params:oauth:grant-type:token-exchange",
    "urn:openid:params:grant-type:ciba",
    "implicit",
    "password",
)
