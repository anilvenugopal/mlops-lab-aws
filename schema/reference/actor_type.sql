-- reference.actor_type  ·  subject: identity  ·  (table)

-- REFERENCE-TABLE PATTERN (every controlled vocabulary; D1 + D1-amend + D9/SKOS)
--   code         text  PK     -- stable machine key + FK target + IRI fragment
--   label        text         -- FE display
--   description  text
--   sort_order   int          -- FE ordering
--   grouping     text         -- optional FE bucket
--   parent_code  text -> self -- hierarchy (= skos:broader/narrower)
--   effective_start_date / effective_end_date  -- validity window (D1-amend);
--                                                  retire = close the window
--   is_active    bool         -- convenience flag (= effective_end_date = '2099-12-31')
--   metadata     jsonb        -- icon/color/extra FE attrs
--   created_at / updated_at
-- Referencing columns elsewhere:  <vocab>_code text -> reference.<vocab>(code)
-- One row per code (code is PK & FK target); in-place label edits are not
-- version-tracked (rare; retire+replace if needed).  Seeds carry v1 enum
-- members verbatim (no silent capability loss).
-- More vocabularies are added to this file as each domain is re-applied.
CREATE TABLE reference.actor_type (
    code                 text        NOT NULL,
    label                text        NOT NULL,
    description          text,
    sort_order           integer     NOT NULL,
    grouping             text,
    parent_code          text,
    effective_start_date date        NOT NULL DEFAULT current_date,
    effective_end_date   date NOT NULL DEFAULT '2099-12-31',
    is_active            boolean      NOT NULL DEFAULT true,
    metadata             jsonb        NOT NULL DEFAULT '{}'::jsonb,
    created_at           timestamptz  NOT NULL DEFAULT now(),
    updated_at           timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT pk_actor_type PRIMARY KEY (code),
    CONSTRAINT fk_actor_type_parent FOREIGN KEY (parent_code)
        REFERENCES reference.actor_type (code) ON DELETE RESTRICT,
    CONSTRAINT uq_actor_type_sort UNIQUE (sort_order),
    CONSTRAINT ck_actor_type_effective CHECK (effective_end_date >= effective_start_date)
);
COMMENT ON TABLE reference.actor_type IS
'Whether an actor is a human or an automation; the discriminator for the core.actor supertype.

@lifecycle reference
@subject identity';
