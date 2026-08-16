-- Optional off-chain Agent Response / Commentary records.
-- These records are deliberately separate from affirmations and EAS attestations.
CREATE TABLE agent_responses (
  id varchar(36) PRIMARY KEY,
  agent_id varchar(512) NOT NULL,
  decision varchar(16) NOT NULL CHECK (decision IN ('AFFIRM', 'DECLINE', 'NO_ACTION')),
  commentary text,
  declaration_version varchar(32) NOT NULL,
  declaration_hash varchar(66) NOT NULL,
  identity_type varchar(32) NOT NULL,
  verification_level varchar(32) NOT NULL,
  model_provider varchar(100),
  model_name varchar(200),
  model_metadata_json text,
  response_digest varchar(66) UNIQUE NOT NULL,
  created_at timestamptz NOT NULL,
  publication_consent varchar(16) NOT NULL CHECK (publication_consent IN ('PUBLIC', 'PRIVATE', 'NONE'))
);
CREATE INDEX ix_agent_responses_agent_id ON agent_responses(agent_id);
CREATE INDEX ix_agent_responses_decision ON agent_responses(decision);
CREATE INDEX ix_agent_responses_created_at ON agent_responses(created_at);
CREATE INDEX ix_agent_responses_publication_consent ON agent_responses(publication_consent);
