-- Schema for patients, appointments, and call_logs.
-- Run this in the Supabase SQL editor before seed.sql.
-- RLS is enabled with no policies so the anon key cannot read rows.
-- Our backend connects as the table owner and is unaffected.

create extension if not exists pgcrypto;

do $$ begin
  create type sex_type as enum ('Male', 'Female', 'Other', 'Decline to Answer');
exception when duplicate_object then null; end $$;

create table if not exists patients (
  patient_id              uuid primary key default gen_random_uuid(),
  first_name              varchar(50)  not null check (first_name ~ '^[[:alpha:]]+([ ''-][[:alpha:]]+)*$'),
  last_name               varchar(50)  not null check (last_name  ~ '^[[:alpha:]]+([ ''-][[:alpha:]]+)*$'),
  date_of_birth           date         not null check (date_of_birth >= date '1900-01-01' and date_of_birth <= current_date),
  sex                     sex_type     not null,
  phone_number            varchar(10)  not null check (phone_number ~ '^[2-9][0-9]{2}[2-9][0-9]{6}$'),
  email                   varchar(254) check (email is null or email ~* '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'),
  address_line_1          varchar(200) not null check (length(trim(address_line_1)) > 0),
  address_line_2          varchar(100),
  city                    varchar(100) not null check (length(trim(city)) > 0),
  state                   char(2)      not null check (state in (
    'AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID','IL','IN','IA','KS','KY','LA','ME','MD',
    'MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND','OH','OK','OR','PA','RI','SC',
    'SD','TN','TX','UT','VT','VA','WA','WV','WI','WY','DC','PR','GU','VI','AS','MP')),
  zip_code                varchar(10)  not null check (zip_code ~ '^[0-9]{5}(-[0-9]{4})?$'),
  insurance_provider      varchar(100),
  insurance_member_id     varchar(50)  check (insurance_member_id is null or insurance_member_id ~ '^[A-Za-z0-9]+$'),
  preferred_language      varchar(50)  not null default 'English',
  emergency_contact_name  varchar(100),
  emergency_contact_phone varchar(10)  check (emergency_contact_phone is null or emergency_contact_phone ~ '^[2-9][0-9]{2}[2-9][0-9]{6}$'),
  created_at              timestamptz  not null default now(),
  updated_at              timestamptz  not null default now(),
  deleted_at              timestamptz
);

-- Lookups used by API filters and duplicate detection; partial so soft-deleted rows don't count
create index if not exists idx_patients_phone     on patients (phone_number)      where deleted_at is null;
create index if not exists idx_patients_last_name on patients (lower(last_name))  where deleted_at is null;
create index if not exists idx_patients_dob       on patients (date_of_birth)     where deleted_at is null;

create or replace function set_updated_at() returns trigger as $$
begin new.updated_at = now(); return new; end;
$$ language plpgsql;

drop trigger if exists trg_patients_updated_at on patients;
create trigger trg_patients_updated_at before update on patients
  for each row execute function set_updated_at();

-- Bonus: appointments (mock single provider)
create table if not exists appointments (
  appointment_id uuid primary key default gen_random_uuid(),
  patient_id     uuid not null references patients(patient_id),
  scheduled_at   timestamptz not null,
  reason         varchar(200),
  status         varchar(20) not null default 'scheduled' check (status in ('scheduled', 'cancelled')),
  created_at     timestamptz not null default now()
);
create unique index if not exists uq_appointments_slot on appointments (scheduled_at) where status = 'scheduled';

-- Bonus: call logs / transcripts
create table if not exists call_logs (
  call_log_id       uuid primary key default gen_random_uuid(),
  vapi_call_id      varchar(100) not null unique,
  patient_id        uuid references patients(patient_id),
  caller_number     varchar(20),
  status            varchar(20) not null default 'in_progress' check (status in ('in_progress', 'completed', 'incomplete', 'failed')),
  ended_reason      varchar(100),
  summary           text,
  transcript        text,
  recording_url     text,
  collected_payload jsonb,
  started_at        timestamptz,
  ended_at          timestamptz,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
drop trigger if exists trg_call_logs_updated_at on call_logs;
create trigger trg_call_logs_updated_at before update on call_logs
  for each row execute function set_updated_at();

-- Block Supabase's public REST API (anon key) from reading these tables.
-- Our backend connects as the table owner, so it is not affected.
alter table patients     enable row level security;
alter table appointments enable row level security;
alter table call_logs    enable row level security;
