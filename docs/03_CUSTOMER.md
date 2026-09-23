# Customer Design

## Customer
id, public_id, name, phone, email, default_address, status, created_at, updated_at.

## CustomerIdentity
customer_id, channel, external_id, display_name, avatar_url, metadata, first_seen_at, last_seen_at.
Unique(channel, external_id).

## Conversation
customer_id, channel, channel_account_id, external_thread_id, status, assigned_user_id, unread_count, last_message_at.

## Merge
Merge Customer, never only Conversation.
Atomically transfer identities, conversations, tags, notes and orders.
Create audit record.
Never auto-merge on name alone.

## Duplicate detection
Use external identity, normalized phone, normalized name and supporting signals.
Candidate suggestion is preferred over automatic merge.
