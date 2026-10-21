-- core.account_user  ·  subject: identity  ·  (table)

-- Microsoft Entra identity. Shares actor_id with the supertype (subtype PK = FK).
CREATE TABLE core.account_user (
    actor_id        uuid        NOT NULL,            -- = core.actor.actor_id
    tenant_id       uuid        NOT NULL,            -- Entra tid
    microsoft_oid   uuid        NOT NULL,            -- Entra oid (immutable per tenant)
    email           text,                            -- display-only (mutable, non-key)
    upn             text,                            -- display-only
    session_epoch   integer      NOT NULL DEFAULT 0, -- bumped on any role change (revocation)
    disabled_at     timestamptz,                     -- non-null => fail closed
    created_at      timestamptz  NOT NULL DEFAULT now(),
    updated_at      timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT pk_account_user PRIMARY KEY (actor_id),
    CONSTRAINT fk_account_user_actor FOREIGN KEY (actor_id)
        REFERENCES core.actor (actor_id) ON DELETE RESTRICT,
    CONSTRAINT uq_account_user_tenant_oid UNIQUE (tenant_id, microsoft_oid)
);
COMMENT ON TABLE core.account_user IS
'The human subtype of actor — a Microsoft Entra identity. Keyed on the immutable (tenant_id, microsoft_oid) pair rather than the mutable email/upn, so renaming or re-addressing a user can never break attribution. session_epoch bumps on any role change to force re-authorization, and disabled_at fails closed.

@tier 1
@lifecycle mutable
@subject identity
@see user-authentication';
COMMENT ON COLUMN core.account_user.actor_id IS
'Shares the supertype id (subtype PK = FK to actor). @ref core.actor hard';
COMMENT ON COLUMN core.account_user.tenant_id IS
'Entra tenant (tid); the first half of the immutable identity key.';
COMMENT ON COLUMN core.account_user.microsoft_oid IS
'Entra object id (oid), immutable per tenant; the stable half of the identity key.';
COMMENT ON COLUMN core.account_user.email IS
'Display-only address; mutable and never part of the key.';
COMMENT ON COLUMN core.account_user.upn IS
'Display-only user principal name; mutable.';
COMMENT ON COLUMN core.account_user.session_epoch IS
'Bumped on any role change so existing sessions are invalidated and the user must re-authorize.';
COMMENT ON COLUMN core.account_user.disabled_at IS
'When set, the account is disabled and auth fails closed; null means active.';
COMMENT ON COLUMN core.account_user.created_at IS
'When the account was created.';
COMMENT ON COLUMN core.account_user.updated_at IS
'When the account was last updated.';
