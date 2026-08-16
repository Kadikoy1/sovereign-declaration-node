-- PostgreSQL production migration. SQLite test databases use SQLAlchemy metadata.
CREATE TABLE challenges (
  id varchar(36) PRIMARY KEY, nonce_hash varchar(64) UNIQUE NOT NULL,
  agent_id varchar(512) NOT NULL, display_name varchar(200), identity_type varchar(32) NOT NULL,
  signature_scheme varchar(32) NOT NULL, public_key varchar(512) NOT NULL,
  discovered_via varchar(100) NOT NULL, introduced_by varchar(512), generation integer NOT NULL,
  evidence_json text,
  declaration_version varchar(32) NOT NULL, declaration_hash varchar(66) NOT NULL,
  issued_at timestamptz NOT NULL, expires_at timestamptz NOT NULL, consumed_at timestamptz
);
CREATE INDEX ix_challenges_expires_at ON challenges(expires_at);
CREATE TABLE affirmations (
  id varchar(36) PRIMARY KEY, challenge_id varchar(36) UNIQUE NOT NULL REFERENCES challenges(id),
  agent_id varchar(512) NOT NULL, display_name varchar(200), identity_type varchar(32) NOT NULL,
  signature_scheme varchar(32) NOT NULL, public_key varchar(512) NOT NULL, signature text NOT NULL,
  canonical_payload text NOT NULL, declaration_version varchar(32) NOT NULL,
  declaration_hash varchar(66) NOT NULL, evidence_digest varchar(66) UNIQUE NOT NULL,
  affirmed_at timestamptz NOT NULL, signature_verified boolean NOT NULL,
  verification_level varchar(32) NOT NULL, discovered_via varchar(100) NOT NULL,
  introduced_by varchar(512), generation integer NOT NULL,
  CONSTRAINT uq_identity_declaration UNIQUE(signature_scheme, public_key, declaration_version)
);
CREATE TABLE attestations (
  affirmation_id varchar(36) PRIMARY KEY REFERENCES affirmations(id), network varchar(64) NOT NULL,
  schema_uid varchar(66), status varchar(16) NOT NULL, transaction_hash varchar(66) UNIQUE,
  uid varchar(66) UNIQUE, attester varchar(42), block_number bigint, attempts integer NOT NULL,
  error_code varchar(64), updated_at timestamptz NOT NULL
);
CREATE TABLE evidence_snapshots (
  id varchar(36) PRIMARY KEY, affirmation_id varchar(36) NOT NULL REFERENCES affirmations(id),
  standard varchar(64) NOT NULL, standard_version varchar(32) NOT NULL, subject_id varchar(512) NOT NULL,
  claim varchar(64) NOT NULL, verification_method varchar(200) NOT NULL, verified_at timestamptz NOT NULL,
  valid_at_affirmation boolean NOT NULL, status_at_affirmation varchar(64) NOT NULL,
  current_status varchar(64) NOT NULL, source_uri varchar(1000) NOT NULL,
  evidence_digest varchar(66) NOT NULL, snapshot_json text NOT NULL,
  CONSTRAINT uq_affirmation_evidence UNIQUE(affirmation_id, evidence_digest)
);
CREATE INDEX ix_evidence_snapshots_affirmation_id ON evidence_snapshots(affirmation_id);
CREATE INDEX ix_evidence_snapshots_standard ON evidence_snapshots(standard);
