CREATE TABLE users (
    user_id       SERIAL       PRIMARY KEY,
    email         VARCHAR(255) NOT NULL UNIQUE,
    username      VARCHAR(50)  NOT NULL UNIQUE,
    nickname      VARCHAR(50),
    password_hash VARCHAR(255) NOT NULL,
    created_at    TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE TABLE workspaces (
    workspace_id SERIAL       PRIMARY KEY,
    name         VARCHAR(100) NOT NULL,
    description  TEXT,
    created_by   INT          NOT NULL REFERENCES users(user_id),
    created_at   TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE TABLE workspace_members (
    workspace_id INT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    user_id      INT       NOT NULL REFERENCES users(user_id),
    joined_at    TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (workspace_id, user_id)
);

CREATE TABLE workspace_admins (
    workspace_id INT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    user_id      INT       NOT NULL REFERENCES users(user_id),
    assigned_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (workspace_id, user_id)
);

CREATE TABLE channels (
    channel_id   SERIAL       PRIMARY KEY,
    workspace_id INT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    name         VARCHAR(100),
    channel_type VARCHAR(10)  NOT NULL CHECK (channel_type IN ('public', 'private', 'direct')),
    created_by   INT          NOT NULL REFERENCES users(user_id),
    created_at   TIMESTAMP    NOT NULL DEFAULT NOW(),
    UNIQUE (channel_id, workspace_id)
);

-- Name uniqueness enforced only for non-DM channels
CREATE UNIQUE INDEX unique_channel_name
    ON channels (workspace_id, name)
    WHERE channel_type != 'direct';

-- ── CHANNEL MEMBERS ──────────────────────────────────────────────────────────
CREATE TABLE channel_members (
    channel_id   INT       NOT NULL,
    workspace_id INT       NOT NULL,
    user_id      INT       NOT NULL,
    joined_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (channel_id, user_id),
    -- Ensures the channel actually belongs to the stated workspace
    FOREIGN KEY (channel_id, workspace_id)
    REFERENCES channels(channel_id, workspace_id) ON DELETE CASCADE,
    -- Ensures the user is a member of that workspace
    FOREIGN KEY (workspace_id, user_id)
        REFERENCES workspace_members(workspace_id, user_id) ON DELETE CASCADE
);

CREATE TABLE workspace_invitations (
    invitation_id SERIAL      PRIMARY KEY,
    workspace_id INT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    inviter_id    INT         NOT NULL REFERENCES users(user_id),
    invitee_id    INT         NOT NULL REFERENCES users(user_id),
    status        VARCHAR(10) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'accepted', 'declined')),
    invited_at    TIMESTAMP   NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX unique_active_workspace_invitation
    ON workspace_invitations (workspace_id, invitee_id)
    WHERE status = 'pending';

CREATE TABLE channel_invitations (
    invitation_id SERIAL      PRIMARY KEY,
    channel_id INT NOT NULL REFERENCES channels(channel_id) ON DELETE CASCADE,
    inviter_id    INT         NOT NULL REFERENCES users(user_id),
    invitee_id    INT         NOT NULL REFERENCES users(user_id),
    status        VARCHAR(10) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'accepted', 'declined')),
    invited_at    TIMESTAMP   NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX unique_active_channel_invitation
    ON channel_invitations (channel_id, invitee_id)
    WHERE status = 'pending';

CREATE TABLE messages (
    message_id   SERIAL    PRIMARY KEY,
    channel_id   INT       NOT NULL,
    user_id      INT       NOT NULL,
    body         TEXT      NOT NULL,
    -- Generated automatically from body. Powers GIN keyword search.
    -- Insert interface unchanged: application inserts body as plain text.
    body_tsv     TSVECTOR  GENERATED ALWAYS AS
                     (to_tsvector('english', body)) STORED,
    posted_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    --- Ensures the posting user is an explicit member of the channel
    FOREIGN KEY (channel_id) REFERENCES channels(channel_id) on DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- GIN index for full-text keyword search (query 7)
CREATE INDEX messages_body_gin
    ON messages USING GIN (body_tsv);

-- Composite B-tree covers query 5 sort order without a separate sort step
CREATE INDEX idx_messages_channel
    ON messages (channel_id, posted_at, message_id);

-- B-tree indexes on FK columns to keep join chains in queries 6 and 7 fast
CREATE INDEX idx_workspace_members_user ON workspace_members (user_id);
CREATE INDEX idx_channel_members_user   ON channel_members (user_id);
CREATE INDEX idx_messages_user ON messages (user_id);

CREATE OR REPLACE FUNCTION enforce_direct_channel_limit()
RETURNS TRIGGER AS $$
DECLARE
    v_channel_type VARCHAR(10);
    v_workspace_id INT;
    v_existing_member INT;
BEGIN
    SELECT channel_type, workspace_id INTO v_channel_type, v_workspace_id
    FROM channels WHERE channel_id = NEW.channel_id;

    IF v_channel_type = 'direct' THEN
        IF (SELECT COUNT(*) FROM channel_members
            WHERE channel_id = NEW.channel_id) >= 2 THEN
            RAISE EXCEPTION
                'Direct channels cannot have more than 2 members';
        END IF;

        IF (SELECT COUNT(*) FROM channel_members
            WHERE channel_id = NEW.channel_id) = 1 THEN
            SELECT user_id INTO v_existing_member
            FROM channel_members
            WHERE channel_id = NEW.channel_id;
            IF EXISTS (
                SELECT 1
                FROM channel_members cm1
                JOIN channel_members cm2 ON cm1.channel_id = cm2.channel_id
                JOIN channels c ON c.channel_id = cm1.channel_id
                WHERE c.channel_type  = 'direct' AND c.workspace_id  = v_workspace_id AND cm1.user_id = NEW.user_id
                AND cm2.user_id = v_existing_member
                AND cm1.channel_id != NEW.channel_id
            ) THEN
                RAISE EXCEPTION
                    'A direct channel exists between these two users in this workspace';
            END IF;
        END IF;

    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER check_direct_channel_limit
    BEFORE INSERT ON channel_members
    FOR EACH ROW EXECUTE FUNCTION enforce_direct_channel_limit();

CREATE OR REPLACE FUNCTION delete_workspace_on_last_member()
RETURNS TRIGGER AS $$
BEGIN
    IF (SELECT COUNT(*) FROM workspace_members
        WHERE workspace_id = OLD.workspace_id) <= 1 THEN
        DELETE FROM workspaces
        WHERE workspace_id = OLD.workspace_id;
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER check_workspace_last_member
    BEFORE DELETE ON workspace_members
    FOR EACH ROW
    EXECUTE FUNCTION delete_workspace_on_last_member();


