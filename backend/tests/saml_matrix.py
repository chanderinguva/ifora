"""IFORA-25: the SAML IdP interoperability matrix as data (same shape as `oidc_matrix.py`).

Each row ties a SAML requirement to the tests that prove it. `test_saml_interop_matrix.py` checks the tests exist and
`scripts/saml_matrix.py` runs them and writes the document with real results. Test reference: "<file>::<test>" under backend/tests.
"""

from typing import NamedTuple, Tuple


class Row(NamedTuple):
    id: str
    spec: str
    clause: str
    requirement: str
    tests: Tuple[str, ...]


I = "test_saml_interop_matrix.py::"
S = "test_saml.py::"
L = "test_saml_cert_lifecycle.py::"
K = "test_key_encryption_separation.py::"

ROWS = (
    Row("S1", "SAML Core 2.0", "5.4", "Signature on the assertion, the response or both, valid for two independent validators",
        (I + "test_idp_initiated_response_is_accepted_by_both_validators",)),
    Row("S2", "SAML Core 2.0", "2.2.2", "NameID formats: emailAddress, persistent (pairwise per SP), unspecified",
        (I + "test_idp_initiated_response_is_accepted_by_both_validators", S + "test_persistent_name_id_is_stable_and_pairwise")),
    Row("S3", "SAML Core 2.0", "2.7.3", "Attribute statements and mapping reach the SP unchanged",
        (I + "test_idp_initiated_response_is_accepted_by_both_validators", I + "test_end_to_end_response_over_http_is_accepted_by_both_validators")),
    Row("S4", "SAML Core 2.0", "2.5.1", "AudienceRestriction: a different audience is refused",
        (I + "test_a_wrong_audience_is_refused",)),
    Row("S5", "SAML Profiles 4.1.4.3", "Destination / Recipient", "A response addressed to another ACS is refused",
        (I + "test_a_wrong_destination_is_refused",)),
    Row("S6", "SAML Profiles 4.1.4.2", "InResponseTo", "SP-initiated: the response answers the request; a mismatch is refused; each request is single use",
        (I + "test_sp_initiated_in_response_to_is_checked_by_both_validators", S + "test_sp_initiated_flow_is_single_use_and_in_response_to")),
    Row("S7", "SAML Core 2.0", "2.5.1", "NotBefore / NotOnOrAfter: expired and not-yet-valid assertions are refused; modest skew tolerated",
        (I + "test_an_expired_assertion_is_refused", I + "test_an_assertion_that_is_not_yet_valid_is_refused", I + "test_modest_clock_skew_is_tolerated")),
    Row("S8", "SAML Bindings 2.0", "3.4 / 3.5", "HTTP-Redirect and HTTP-POST bindings; RelayState returned",
        (S + "test_sp_initiated_flow_is_single_use_and_in_response_to", S + "test_post_binding_works_too")),
    Row("S9", "SAML Metadata 2.0", "2.4.3", "Metadata publishes the entity id, SSO endpoint and the certificate that signs",
        (I + "test_the_published_metadata_matches_what_signs", S + "test_metadata_describes_the_idp")),
    Row("S10", "XML-DSig / OWASP", "tampering", "A modified assertion or attribute is refused",
        (I + "test_a_tampered_assertion_is_refused_by_both_validators", I + "test_a_tampered_attribute_value_is_refused")),
    Row("S11", "XML-DSig / OWASP", "signature wrapping", "A relocated signed assertion with a forged one in its place is refused; one assertion only",
        (I + "test_a_wrapped_signature_is_refused_by_both_validators", I + "test_a_second_assertion_beside_the_signed_one_is_refused")),
    Row("S12", "SAML Core 2.0", "signing policy", "An unsigned response, or one signed in the wrong place for the SP's policy, is refused",
        (I + "test_an_unsigned_response_is_refused", I + "test_signing_policy_mismatch_is_refused")),
    Row("S13", "XML-DSig", "trust", "A response signed by a key the SP does not pin is refused",
        (I + "test_a_response_signed_by_another_key_is_refused",)),
    Row("S14", "XML hardening", "XXE / DTD", "DTDs and entities in requests and metadata are rejected",
        (S + "test_import_sp_metadata_and_rejects_dtd", S + "test_bad_requests_never_reach_the_sp")),
    Row("S15", "Tenancy", "isolation", "Another tenant's SAML app and SP are not reachable (404 or refused)",
        (I + "test_another_tenants_saml_app_does_not_exist_for_this_tenant",)),
    Row("S16", "Key hygiene", "rotation", "Staged cert is published before it signs; promotion switches signing; both are audited",
        (L + "test_a_staged_certificate_is_published_before_it_signs", L + "test_promote_switches_signing_and_keeps_the_old_certificate_published")),
    Row("S17", "Key hygiene", "lifetime", "New certificates last at most the configured period; the admin API reports days to expiry",
        (L + "test_new_certificates_use_the_configured_validity_and_report_days_to_expiry",)),
    Row("S18", "Key hygiene", "key separation", "A SAML signing key is not decryptable with the OIDC key or subkey; existing rows still decrypt",
        (K + "test_a_saml_key_does_not_decrypt_with_the_oidc_subkey_or_the_oidc_key",
         K + "test_legacy_rows_are_still_read_and_the_migration_rewraps_them_both_ways")),
)
