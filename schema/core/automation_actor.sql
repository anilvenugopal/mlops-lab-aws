-- core.automation_actor  ·  subject: identity  ·  (table)

-- Named automated processes (the harness/runtime per app, named jobs).
CREATE TABLE core.automation_actor (
    actor_id          uuid       NOT NULL,           -- = core.actor.actor_id
    automation_name   text       NOT NULL,           -- e.g. 'equity-research-runner'
    application_id    uuid,                            -- optional: app it acts on behalf of
                                                       -- (FK -> core.application added in the intake domain)
    deployment_cluster_id uuid,                        -- soft ref -> core.deployment_cluster (no FK; nullable).
                                                       -- ONE automation_actor per cluster (not per instance) to avoid
                                                       -- actor proliferation from pod restarts. Worker host identity is
                                                       -- carried on execution_run_status.worker_node_id. D6.
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_automation_actor PRIMARY KEY (actor_id),
    CONSTRAINT fk_automation_actor_actor FOREIGN KEY (actor_id)
        REFERENCES core.actor (actor_id) ON DELETE RESTRICT,
    CONSTRAINT uq_automation_actor_name UNIQUE (automation_name)
);
COMMENT ON TABLE core.automation_actor IS
'The automation subtype of actor — a named machine principal such as the per-cluster harness runtime or a named job. One automation_actor per cluster, not per instance, so pod restarts do not proliferate identities; the worker host is recorded on the run event instead (D6, ADR-0010).

@tier 1
@lifecycle mutable
@subject identity
@decision D6
@adr 0010';
COMMENT ON COLUMN core.automation_actor.actor_id IS
'Shares the supertype id (subtype PK = FK to actor). @ref core.actor hard';
COMMENT ON COLUMN core.automation_actor.automation_name IS
'Stable name of the automated process (e.g. a per-app harness runner); unique.';
COMMENT ON COLUMN core.automation_actor.application_id IS
'The application it acts on behalf of, when scoped to one. @ref core.application hard';
COMMENT ON COLUMN core.automation_actor.deployment_cluster_id IS
'The cluster this automation principal represents; one actor per cluster to avoid identity churn from pod restarts (ADR-0010). @ref core.deployment_cluster soft';
COMMENT ON COLUMN core.automation_actor.created_at IS
'When the automation actor was created.';
COMMENT ON COLUMN core.automation_actor.updated_at IS
'When it was last updated.';
