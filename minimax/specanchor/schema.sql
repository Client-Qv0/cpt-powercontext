-- SpecAnchor engineering-material index (seekdb / OceanBase MySQL mode).
-- One project namespace per imported repository.  Re-importing a spec creates a
-- new revision and deactivates the old one; retrieval only reads active rows.

CREATE TABLE IF NOT EXISTS sa_projects (
  project        VARCHAR(64)  NOT NULL,
  root_path      VARCHAR(512) NOT NULL,
  updated_at     DATETIME(6)  NOT NULL,
  PRIMARY KEY (project)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sa_import_runs (
  id             BIGINT       NOT NULL AUTO_INCREMENT,
  project        VARCHAR(64)  NOT NULL,
  root_path      VARCHAR(512) NOT NULL,
  started_at     DATETIME(6)  NOT NULL,
  finished_at    DATETIME(6)  NULL,
  status         VARCHAR(32)  NOT NULL,
  spec_count     INT          NOT NULL DEFAULT 0,
  code_count     INT          NOT NULL DEFAULT 0,
  test_count     INT          NOT NULL DEFAULT 0,
  note           TEXT         NULL,
  PRIMARY KEY (id),
  KEY idx_import_project (project, started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sa_spec_docs (
  id             BIGINT       NOT NULL AUTO_INCREMENT,
  project        VARCHAR(64)  NOT NULL,
  doc_path       VARCHAR(255) NOT NULL,
  spec_name      VARCHAR(96)  NOT NULL,
  version        VARCHAR(32)  NULL,
  status         VARCHAR(32)  NULL,
  applies_to     TEXT         NULL,
  content_hash   CHAR(64)     NOT NULL,
  active         TINYINT      NOT NULL DEFAULT 1,
  imported_at    DATETIME(6)  NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_spec_doc_hash (project, doc_path, content_hash),
  KEY idx_spec_doc_active (project, active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sa_spec_sections (
  id             BIGINT       NOT NULL AUTO_INCREMENT,
  project        VARCHAR(64)  NOT NULL,
  doc_path       VARCHAR(255) NOT NULL,
  section_key    VARCHAR(96)  NOT NULL,
  spec_id        VARCHAR(64)  NOT NULL,
  heading        VARCHAR(512) NOT NULL,
  level          SMALLINT     NOT NULL,
  line_start     INT          NOT NULL,
  line_end       INT          NOT NULL,
  body           LONGTEXT     NOT NULL,
  revision       INT          NOT NULL,
  content_hash   CHAR(64)     NOT NULL,
  token_count    INT          NOT NULL DEFAULT 0,
  active         TINYINT      NOT NULL DEFAULT 1,
  imported_at    DATETIME(6)  NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_spec_section_rev (project, doc_path, section_key, revision),
  KEY idx_spec_section_active (project, active),
  KEY idx_spec_section_id (project, spec_id, active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sa_code_symbols (
  id             BIGINT       NOT NULL AUTO_INCREMENT,
  project        VARCHAR(64)  NOT NULL,
  path           VARCHAR(255) NOT NULL,
  module         VARCHAR(255) NOT NULL,
  qualname       VARCHAR(255) NOT NULL,
  kind           VARCHAR(32)  NOT NULL,
  signature      VARCHAR(512) NULL,
  lineno         INT          NOT NULL,
  end_lineno     INT          NOT NULL,
  source         LONGTEXT     NOT NULL,
  docstring      TEXT         NULL,
  revision       INT          NOT NULL,
  content_hash   CHAR(64)     NOT NULL,
  token_count    INT          NOT NULL DEFAULT 0,
  active         TINYINT      NOT NULL DEFAULT 1,
  imported_at    DATETIME(6)  NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_code_rev (project, path, qualname, revision),
  KEY idx_code_active (project, active),
  KEY idx_code_path (project, path, active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sa_tests (
  id             BIGINT       NOT NULL AUTO_INCREMENT,
  project        VARCHAR(64)  NOT NULL,
  path           VARCHAR(255) NOT NULL,
  test_id        VARCHAR(255) NOT NULL,
  qualname       VARCHAR(255) NOT NULL,
  kind           VARCHAR(32)  NOT NULL,
  lineno         INT          NOT NULL,
  end_lineno     INT          NOT NULL,
  source         LONGTEXT     NOT NULL,
  docstring      TEXT         NULL,
  covers         TEXT         NULL,
  imports        TEXT         NULL,
  revision       INT          NOT NULL,
  content_hash   CHAR(64)     NOT NULL,
  token_count    INT          NOT NULL DEFAULT 0,
  active         TINYINT      NOT NULL DEFAULT 1,
  imported_at    DATETIME(6)  NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_test_rev (project, path, test_id, revision),
  KEY idx_test_active (project, active),
  KEY idx_test_path (project, path, active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sa_terms (
  project        VARCHAR(64) NOT NULL,
  kind           VARCHAR(16) NOT NULL,
  ref_id         BIGINT      NOT NULL,
  term           VARCHAR(96) NOT NULL,
  tf             INT         NOT NULL,
  PRIMARY KEY (project, kind, ref_id, term),
  KEY idx_terms_lookup (project, kind, term)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sa_spec_targets (
  project        VARCHAR(64)  NOT NULL,
  doc_path       VARCHAR(255) NOT NULL,
  target_path    VARCHAR(255) NOT NULL,
  PRIMARY KEY (project, doc_path, target_path)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sa_test_imports (
  project        VARCHAR(64)  NOT NULL,
  test_path      VARCHAR(255) NOT NULL,
  module         VARCHAR(255) NOT NULL,
  PRIMARY KEY (project, test_path, module)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sa_spec_changes (
  id             BIGINT       NOT NULL AUTO_INCREMENT,
  project        VARCHAR(64)  NOT NULL,
  doc_path       VARCHAR(255) NOT NULL,
  section_key    VARCHAR(96)  NOT NULL,
  spec_id        VARCHAR(64)  NOT NULL,
  old_hash       CHAR(64)     NULL,
  new_hash       CHAR(64)     NOT NULL,
  old_revision   INT          NULL,
  new_revision   INT          NOT NULL,
  changed_at     DATETIME(6)  NOT NULL,
  PRIMARY KEY (id),
  KEY idx_change_project (project, changed_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS sa_agent_runs (
  id             BIGINT       NOT NULL AUTO_INCREMENT,
  project        VARCHAR(64)  NOT NULL,
  task_id        VARCHAR(128) NOT NULL,
  run_id         VARCHAR(64)  NOT NULL,
  status         VARCHAR(32)  NOT NULL,
  model          VARCHAR(96)  NOT NULL,
  patch_path     VARCHAR(512) NULL,
  test_summary   TEXT         NULL,
  created_at     DATETIME(6)  NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_agent_run (project, run_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
