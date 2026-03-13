--
-- PostgreSQL database dump
--

\restrict l7zj4iievlKCzc7c1QQebO3nty41eDiBQgzblHOJjWOYLKomUppmDSvcO62bXvG

-- Dumped from database version 16.13
-- Dumped by pg_dump version 16.13

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: zarmor
--

CREATE TABLE public.audit_logs (
    id integer NOT NULL,
    action character varying(50) NOT NULL,
    key_id integer,
    email character varying(200),
    detail text,
    ip_address character varying(50),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.audit_logs OWNER TO zarmor;

--
-- Name: audit_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: zarmor
--

CREATE SEQUENCE public.audit_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.audit_logs_id_seq OWNER TO zarmor;

--
-- Name: audit_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zarmor
--

ALTER SEQUENCE public.audit_logs_id_seq OWNED BY public.audit_logs.id;


--
-- Name: ea_sessions; Type: TABLE; Schema: public; Owner: zarmor
--

CREATE TABLE public.ea_sessions (
    id integer NOT NULL,
    account_id character varying(50) NOT NULL,
    session_id character varying(50) NOT NULL,
    magic character varying(50),
    license_key character varying(60),
    equity double precision,
    balance double precision,
    status character varying(20) NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    last_ping timestamp with time zone DEFAULT now() NOT NULL,
    ended_at timestamp with time zone,
    meta_json text
);


ALTER TABLE public.ea_sessions OWNER TO zarmor;

--
-- Name: ea_sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: zarmor
--

CREATE SEQUENCE public.ea_sessions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.ea_sessions_id_seq OWNER TO zarmor;

--
-- Name: ea_sessions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zarmor
--

ALTER SEQUENCE public.ea_sessions_id_seq OWNED BY public.ea_sessions.id;


--
-- Name: license_activations; Type: TABLE; Schema: public; Owner: zarmor
--

CREATE TABLE public.license_activations (
    id integer NOT NULL,
    license_key character varying(60) NOT NULL,
    account_id character varying(50) NOT NULL,
    magic character varying(50),
    first_seen timestamp with time zone DEFAULT now() NOT NULL,
    last_seen timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.license_activations OWNER TO zarmor;

--
-- Name: license_activations_id_seq; Type: SEQUENCE; Schema: public; Owner: zarmor
--

CREATE SEQUENCE public.license_activations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.license_activations_id_seq OWNER TO zarmor;

--
-- Name: license_activations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zarmor
--

ALTER SEQUENCE public.license_activations_id_seq OWNED BY public.license_activations.id;


--
-- Name: license_keys; Type: TABLE; Schema: public; Owner: zarmor
--

CREATE TABLE public.license_keys (
    id integer NOT NULL,
    key character varying(40),
    buyer_name character varying(200) NOT NULL,
    buyer_email character varying(200) NOT NULL,
    tier character varying(50) NOT NULL,
    amount_usd double precision NOT NULL,
    payment_method character varying(20),
    status character varying(20) NOT NULL,
    is_trial boolean NOT NULL,
    activated_at timestamp with time zone,
    expires_at timestamp with time zone,
    lark_record_id character varying(100),
    email_sent boolean DEFAULT false,
    email_sent_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    ip_address character varying(50),
    notes text,
    max_machines integer DEFAULT 1,
    bound_mt5_id character varying(50),
    license_key character varying(60)
);


ALTER TABLE public.license_keys OWNER TO zarmor;

--
-- Name: license_keys_id_seq; Type: SEQUENCE; Schema: public; Owner: zarmor
--

CREATE SEQUENCE public.license_keys_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.license_keys_id_seq OWNER TO zarmor;

--
-- Name: license_keys_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zarmor
--

ALTER SEQUENCE public.license_keys_id_seq OWNED BY public.license_keys.id;


--
-- Name: neural_profiles; Type: TABLE; Schema: public; Owner: zarmor
--

CREATE TABLE public.neural_profiles (
    id integer NOT NULL,
    account_id character varying(50) NOT NULL,
    trader_archetype character varying(50) NOT NULL,
    historical_win_rate double precision NOT NULL,
    historical_rr double precision NOT NULL,
    optimization_bias character varying(50) NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.neural_profiles OWNER TO zarmor;

--
-- Name: neural_profiles_id_seq; Type: SEQUENCE; Schema: public; Owner: zarmor
--

CREATE SEQUENCE public.neural_profiles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.neural_profiles_id_seq OWNER TO zarmor;

--
-- Name: neural_profiles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zarmor
--

ALTER SEQUENCE public.neural_profiles_id_seq OWNED BY public.neural_profiles.id;


--
-- Name: risk_hard_limits; Type: TABLE; Schema: public; Owner: zarmor
--

CREATE TABLE public.risk_hard_limits (
    id integer NOT NULL,
    account_id character varying(50) NOT NULL,
    daily_limit_money double precision NOT NULL,
    max_dd double precision NOT NULL,
    dd_type character varying(20) NOT NULL,
    consistency double precision NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.risk_hard_limits OWNER TO zarmor;

--
-- Name: risk_hard_limits_id_seq; Type: SEQUENCE; Schema: public; Owner: zarmor
--

CREATE SEQUENCE public.risk_hard_limits_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.risk_hard_limits_id_seq OWNER TO zarmor;

--
-- Name: risk_hard_limits_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zarmor
--

ALTER SEQUENCE public.risk_hard_limits_id_seq OWNED BY public.risk_hard_limits.id;


--
-- Name: risk_tacticals; Type: TABLE; Schema: public; Owner: zarmor
--

CREATE TABLE public.risk_tacticals (
    id integer NOT NULL,
    account_id character varying(50) NOT NULL,
    params_json text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.risk_tacticals OWNER TO zarmor;

--
-- Name: risk_tacticals_id_seq; Type: SEQUENCE; Schema: public; Owner: zarmor
--

CREATE SEQUENCE public.risk_tacticals_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.risk_tacticals_id_seq OWNER TO zarmor;

--
-- Name: risk_tacticals_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zarmor
--

ALTER SEQUENCE public.risk_tacticals_id_seq OWNED BY public.risk_tacticals.id;


--
-- Name: session_history; Type: TABLE; Schema: public; Owner: zarmor
--

CREATE TABLE public.session_history (
    id integer NOT NULL,
    account_id character varying(50) NOT NULL,
    session_id character varying(50),
    date character varying(20),
    opening_balance double precision,
    closing_balance double precision,
    pnl double precision,
    max_dd double precision,
    trade_count integer,
    win_count integer,
    loss_count integer,
    summary text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.session_history OWNER TO zarmor;

--
-- Name: session_history_id_seq; Type: SEQUENCE; Schema: public; Owner: zarmor
--

CREATE SEQUENCE public.session_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.session_history_id_seq OWNER TO zarmor;

--
-- Name: session_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zarmor
--

ALTER SEQUENCE public.session_history_id_seq OWNED BY public.session_history.id;


--
-- Name: system_states; Type: TABLE; Schema: public; Owner: zarmor
--

CREATE TABLE public.system_states (
    id integer NOT NULL,
    account_id character varying(50) NOT NULL,
    state_json text,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.system_states OWNER TO zarmor;

--
-- Name: system_states_id_seq; Type: SEQUENCE; Schema: public; Owner: zarmor
--

CREATE SEQUENCE public.system_states_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.system_states_id_seq OWNER TO zarmor;

--
-- Name: system_states_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zarmor
--

ALTER SEQUENCE public.system_states_id_seq OWNED BY public.system_states.id;


--
-- Name: telegram_configs; Type: TABLE; Schema: public; Owner: zarmor
--

CREATE TABLE public.telegram_configs (
    id integer NOT NULL,
    account_id character varying(50) NOT NULL,
    chat_id character varying(50),
    is_active boolean NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.telegram_configs OWNER TO zarmor;

--
-- Name: telegram_configs_id_seq; Type: SEQUENCE; Schema: public; Owner: zarmor
--

CREATE SEQUENCE public.telegram_configs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.telegram_configs_id_seq OWNER TO zarmor;

--
-- Name: telegram_configs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zarmor
--

ALTER SEQUENCE public.telegram_configs_id_seq OWNED BY public.telegram_configs.id;


--
-- Name: trade_history; Type: TABLE; Schema: public; Owner: zarmor
--

CREATE TABLE public.trade_history (
    id integer NOT NULL,
    account_id character varying(50) NOT NULL,
    session_id character varying(50),
    ticket character varying(50),
    symbol character varying(20),
    trade_type character varying(10),
    volume double precision,
    open_price double precision,
    close_price double precision,
    pnl double precision,
    rr_ratio double precision,
    risk_amount double precision,
    actual_rr double precision,
    opened_at timestamp with time zone,
    closed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.trade_history OWNER TO zarmor;

--
-- Name: trade_history_id_seq; Type: SEQUENCE; Schema: public; Owner: zarmor
--

CREATE SEQUENCE public.trade_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.trade_history_id_seq OWNER TO zarmor;

--
-- Name: trade_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zarmor
--

ALTER SEQUENCE public.trade_history_id_seq OWNED BY public.trade_history.id;


--
-- Name: trading_accounts; Type: TABLE; Schema: public; Owner: zarmor
--

CREATE TABLE public.trading_accounts (
    id integer NOT NULL,
    account_id character varying(50) NOT NULL,
    alias character varying(100),
    is_locked boolean NOT NULL,
    arm boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.trading_accounts OWNER TO zarmor;

--
-- Name: trading_accounts_id_seq; Type: SEQUENCE; Schema: public; Owner: zarmor
--

CREATE SEQUENCE public.trading_accounts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.trading_accounts_id_seq OWNER TO zarmor;

--
-- Name: trading_accounts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zarmor
--

ALTER SEQUENCE public.trading_accounts_id_seq OWNED BY public.trading_accounts.id;


--
-- Name: audit_logs id; Type: DEFAULT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.audit_logs ALTER COLUMN id SET DEFAULT nextval('public.audit_logs_id_seq'::regclass);


--
-- Name: ea_sessions id; Type: DEFAULT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.ea_sessions ALTER COLUMN id SET DEFAULT nextval('public.ea_sessions_id_seq'::regclass);


--
-- Name: license_activations id; Type: DEFAULT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.license_activations ALTER COLUMN id SET DEFAULT nextval('public.license_activations_id_seq'::regclass);


--
-- Name: license_keys id; Type: DEFAULT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.license_keys ALTER COLUMN id SET DEFAULT nextval('public.license_keys_id_seq'::regclass);


--
-- Name: neural_profiles id; Type: DEFAULT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.neural_profiles ALTER COLUMN id SET DEFAULT nextval('public.neural_profiles_id_seq'::regclass);


--
-- Name: risk_hard_limits id; Type: DEFAULT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.risk_hard_limits ALTER COLUMN id SET DEFAULT nextval('public.risk_hard_limits_id_seq'::regclass);


--
-- Name: risk_tacticals id; Type: DEFAULT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.risk_tacticals ALTER COLUMN id SET DEFAULT nextval('public.risk_tacticals_id_seq'::regclass);


--
-- Name: session_history id; Type: DEFAULT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.session_history ALTER COLUMN id SET DEFAULT nextval('public.session_history_id_seq'::regclass);


--
-- Name: system_states id; Type: DEFAULT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.system_states ALTER COLUMN id SET DEFAULT nextval('public.system_states_id_seq'::regclass);


--
-- Name: telegram_configs id; Type: DEFAULT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.telegram_configs ALTER COLUMN id SET DEFAULT nextval('public.telegram_configs_id_seq'::regclass);


--
-- Name: trade_history id; Type: DEFAULT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.trade_history ALTER COLUMN id SET DEFAULT nextval('public.trade_history_id_seq'::regclass);


--
-- Name: trading_accounts id; Type: DEFAULT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.trading_accounts ALTER COLUMN id SET DEFAULT nextval('public.trading_accounts_id_seq'::regclass);


--
-- Data for Name: audit_logs; Type: TABLE DATA; Schema: public; Owner: zarmor
--

COPY public.audit_logs (id, action, key_id, email, detail, ip_address, created_at) FROM stdin;
1	CHECKOUT	1	dangphi9333@gmail.com	tier=STARTER_TRIAL amount=0.0 method=TRIAL_FREE trial=True	113.23.111.9	2026-03-05 14:48:56.40609+00
2	CHECKOUT	2	dangphi9339@gmail.com	tier=STARTER_TRIAL amount=0.0 method=TRIAL_FREE trial=True	113.23.111.9	2026-03-05 14:50:31.027334+00
3	CHECKOUT	3	flyhomecompany@gmail.com	tier=STARTER_TRIAL amount=0.0 method=TRIAL_FREE trial=True lark=False email=False	113.23.110.140	2026-03-06 06:34:40.280288+00
\.


--
-- Data for Name: ea_sessions; Type: TABLE DATA; Schema: public; Owner: zarmor
--

COPY public.ea_sessions (id, account_id, session_id, magic, license_key, equity, balance, status, started_at, last_ping, ended_at, meta_json) FROM stdin;
\.


--
-- Data for Name: license_activations; Type: TABLE DATA; Schema: public; Owner: zarmor
--

COPY public.license_activations (id, license_key, account_id, magic, first_seen, last_seen) FROM stdin;
1	ZARMOR-F6EC1-27EA3	413408816	900001	2026-03-07 04:30:34.160221+00	2026-03-07 04:30:34.160221+00
\.


--
-- Data for Name: license_keys; Type: TABLE DATA; Schema: public; Owner: zarmor
--

COPY public.license_keys (id, key, buyer_name, buyer_email, tier, amount_usd, payment_method, status, is_trial, activated_at, expires_at, lark_record_id, email_sent, email_sent_at, created_at, updated_at, ip_address, notes, max_machines, bound_mt5_id, license_key) FROM stdin;
32	\N	dangphi	dangphi9333@gmail.com	STARTER_TRIAL	0	TRIAL_FREE	ACTIVE	t	\N	2026-03-14 03:23:13.318768+00	\N	t	\N	2026-03-07 03:23:13.486044+00	2026-03-07 03:23:16.49484+00	\N	\N	1	\N	ZARMOR-54F59-48305
33	\N	12123	dangphi9339@gmail.com	STARTER_TRIAL	0	TRIAL_FREE	ACTIVE	t	\N	2026-03-14 03:31:55.775925+00	\N	t	\N	2026-03-07 03:31:55.788052+00	2026-03-07 03:31:58.586886+00	\N	\N	1	\N	ZARMOR-F6EC1-27EA3
\.


--
-- Data for Name: neural_profiles; Type: TABLE DATA; Schema: public; Owner: zarmor
--

COPY public.neural_profiles (id, account_id, trader_archetype, historical_win_rate, historical_rr, optimization_bias, updated_at) FROM stdin;
1	413408416	SNIPER	40	1.5	HALF_KELLY	2026-03-06 22:17:54.82274+00
2	413408816	SNIPER	40	1.5	HALF_KELLY	2026-03-06 23:01:42.963031+00
3	413408813	SNIPER	40	1.5	HALF_KELLY	2026-03-07 03:52:52.554859+00
\.


--
-- Data for Name: risk_hard_limits; Type: TABLE DATA; Schema: public; Owner: zarmor
--

COPY public.risk_hard_limits (id, account_id, daily_limit_money, max_dd, dd_type, consistency, updated_at) FROM stdin;
1	413408416	150	10	STATIC	97	2026-03-06 22:17:54.82274+00
2	413408816	150	10	STATIC	97	2026-03-06 23:01:42.963031+00
3	413408813	150	10	STATIC	97	2026-03-07 03:52:52.554859+00
\.


--
-- Data for Name: risk_tacticals; Type: TABLE DATA; Schema: public; Owner: zarmor
--

COPY public.risk_tacticals (id, account_id, params_json, updated_at) FROM stdin;
1	413408416	\N	2026-03-06 22:17:54.82274+00
2	413408816	\N	2026-03-06 23:01:42.963031+00
3	413408813	\N	2026-03-07 03:52:52.554859+00
\.


--
-- Data for Name: session_history; Type: TABLE DATA; Schema: public; Owner: zarmor
--

COPY public.session_history (id, account_id, session_id, date, opening_balance, closing_balance, pnl, max_dd, trade_count, win_count, loss_count, summary, created_at) FROM stdin;
\.


--
-- Data for Name: system_states; Type: TABLE DATA; Schema: public; Owner: zarmor
--

COPY public.system_states (id, account_id, state_json, updated_at) FROM stdin;
1	413408416	\N	2026-03-06 22:17:54.82274+00
2	413408816	\N	2026-03-06 23:01:42.963031+00
3	413408813	\N	2026-03-07 03:52:52.554859+00
\.


--
-- Data for Name: telegram_configs; Type: TABLE DATA; Schema: public; Owner: zarmor
--

COPY public.telegram_configs (id, account_id, chat_id, is_active, updated_at) FROM stdin;
1	413408416	7976137362	t	2026-03-06 22:17:54.82274+00
2	413408816	7976137362	t	2026-03-06 23:01:42.963031+00
3	413408813		t	2026-03-07 03:52:52.554859+00
\.


--
-- Data for Name: trade_history; Type: TABLE DATA; Schema: public; Owner: zarmor
--

COPY public.trade_history (id, account_id, session_id, ticket, symbol, trade_type, volume, open_price, close_price, pnl, rr_ratio, risk_amount, actual_rr, opened_at, closed_at, created_at) FROM stdin;
\.


--
-- Data for Name: trading_accounts; Type: TABLE DATA; Schema: public; Owner: zarmor
--

COPY public.trading_accounts (id, account_id, alias, is_locked, arm, created_at, updated_at) FROM stdin;
1	413408416	Trader 413408416	f	f	2026-03-06 22:17:54.82274+00	2026-03-06 22:17:54.82274+00
2	413408816	Trader 413408816	f	f	2026-03-06 23:01:42.963031+00	2026-03-06 23:01:42.963031+00
3	413408813	Trader 413408813	f	f	2026-03-07 03:52:52.554859+00	2026-03-07 03:52:52.554859+00
\.


--
-- Name: audit_logs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: zarmor
--

SELECT pg_catalog.setval('public.audit_logs_id_seq', 3, true);


--
-- Name: ea_sessions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: zarmor
--

SELECT pg_catalog.setval('public.ea_sessions_id_seq', 1, false);


--
-- Name: license_activations_id_seq; Type: SEQUENCE SET; Schema: public; Owner: zarmor
--

SELECT pg_catalog.setval('public.license_activations_id_seq', 1, true);


--
-- Name: license_keys_id_seq; Type: SEQUENCE SET; Schema: public; Owner: zarmor
--

SELECT pg_catalog.setval('public.license_keys_id_seq', 33, true);


--
-- Name: neural_profiles_id_seq; Type: SEQUENCE SET; Schema: public; Owner: zarmor
--

SELECT pg_catalog.setval('public.neural_profiles_id_seq', 3, true);


--
-- Name: risk_hard_limits_id_seq; Type: SEQUENCE SET; Schema: public; Owner: zarmor
--

SELECT pg_catalog.setval('public.risk_hard_limits_id_seq', 3, true);


--
-- Name: risk_tacticals_id_seq; Type: SEQUENCE SET; Schema: public; Owner: zarmor
--

SELECT pg_catalog.setval('public.risk_tacticals_id_seq', 3, true);


--
-- Name: session_history_id_seq; Type: SEQUENCE SET; Schema: public; Owner: zarmor
--

SELECT pg_catalog.setval('public.session_history_id_seq', 1, false);


--
-- Name: system_states_id_seq; Type: SEQUENCE SET; Schema: public; Owner: zarmor
--

SELECT pg_catalog.setval('public.system_states_id_seq', 3, true);


--
-- Name: telegram_configs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: zarmor
--

SELECT pg_catalog.setval('public.telegram_configs_id_seq', 3, true);


--
-- Name: trade_history_id_seq; Type: SEQUENCE SET; Schema: public; Owner: zarmor
--

SELECT pg_catalog.setval('public.trade_history_id_seq', 1, false);


--
-- Name: trading_accounts_id_seq; Type: SEQUENCE SET; Schema: public; Owner: zarmor
--

SELECT pg_catalog.setval('public.trading_accounts_id_seq', 3, true);


--
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- Name: ea_sessions ea_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.ea_sessions
    ADD CONSTRAINT ea_sessions_pkey PRIMARY KEY (id);


--
-- Name: ea_sessions ea_sessions_session_id_key; Type: CONSTRAINT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.ea_sessions
    ADD CONSTRAINT ea_sessions_session_id_key UNIQUE (session_id);


--
-- Name: license_activations license_activations_pkey; Type: CONSTRAINT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.license_activations
    ADD CONSTRAINT license_activations_pkey PRIMARY KEY (id);


--
-- Name: license_keys license_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.license_keys
    ADD CONSTRAINT license_keys_pkey PRIMARY KEY (id);


--
-- Name: neural_profiles neural_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.neural_profiles
    ADD CONSTRAINT neural_profiles_pkey PRIMARY KEY (id);


--
-- Name: risk_hard_limits risk_hard_limits_pkey; Type: CONSTRAINT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.risk_hard_limits
    ADD CONSTRAINT risk_hard_limits_pkey PRIMARY KEY (id);


--
-- Name: risk_tacticals risk_tacticals_pkey; Type: CONSTRAINT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.risk_tacticals
    ADD CONSTRAINT risk_tacticals_pkey PRIMARY KEY (id);


--
-- Name: session_history session_history_pkey; Type: CONSTRAINT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.session_history
    ADD CONSTRAINT session_history_pkey PRIMARY KEY (id);


--
-- Name: session_history session_history_session_id_key; Type: CONSTRAINT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.session_history
    ADD CONSTRAINT session_history_session_id_key UNIQUE (session_id);


--
-- Name: system_states system_states_pkey; Type: CONSTRAINT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.system_states
    ADD CONSTRAINT system_states_pkey PRIMARY KEY (id);


--
-- Name: telegram_configs telegram_configs_pkey; Type: CONSTRAINT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.telegram_configs
    ADD CONSTRAINT telegram_configs_pkey PRIMARY KEY (id);


--
-- Name: trade_history trade_history_pkey; Type: CONSTRAINT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.trade_history
    ADD CONSTRAINT trade_history_pkey PRIMARY KEY (id);


--
-- Name: trading_accounts trading_accounts_pkey; Type: CONSTRAINT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.trading_accounts
    ADD CONSTRAINT trading_accounts_pkey PRIMARY KEY (id);


--
-- Name: license_activations uq_lic_account; Type: CONSTRAINT; Schema: public; Owner: zarmor
--

ALTER TABLE ONLY public.license_activations
    ADD CONSTRAINT uq_lic_account UNIQUE (license_key, account_id);


--
-- Name: ix_ea_sessions_account_id; Type: INDEX; Schema: public; Owner: zarmor
--

CREATE INDEX ix_ea_sessions_account_id ON public.ea_sessions USING btree (account_id);


--
-- Name: ix_la_account_id; Type: INDEX; Schema: public; Owner: zarmor
--

CREATE INDEX ix_la_account_id ON public.license_activations USING btree (account_id);


--
-- Name: ix_lic_bound_mt5; Type: INDEX; Schema: public; Owner: zarmor
--

CREATE INDEX ix_lic_bound_mt5 ON public.license_keys USING btree (bound_mt5_id);


--
-- Name: ix_lic_buyer_email; Type: INDEX; Schema: public; Owner: zarmor
--

CREATE INDEX ix_lic_buyer_email ON public.license_keys USING btree (buyer_email);


--
-- Name: ix_license_activations_license_key; Type: INDEX; Schema: public; Owner: zarmor
--

CREATE INDEX ix_license_activations_license_key ON public.license_activations USING btree (license_key);


--
-- Name: ix_license_keys_buyer_email; Type: INDEX; Schema: public; Owner: zarmor
--

CREATE INDEX ix_license_keys_buyer_email ON public.license_keys USING btree (buyer_email);


--
-- Name: ix_license_keys_key; Type: INDEX; Schema: public; Owner: zarmor
--

CREATE UNIQUE INDEX ix_license_keys_key ON public.license_keys USING btree (key);


--
-- Name: ix_neural_profiles_account_id; Type: INDEX; Schema: public; Owner: zarmor
--

CREATE UNIQUE INDEX ix_neural_profiles_account_id ON public.neural_profiles USING btree (account_id);


--
-- Name: ix_risk_hard_limits_account_id; Type: INDEX; Schema: public; Owner: zarmor
--

CREATE UNIQUE INDEX ix_risk_hard_limits_account_id ON public.risk_hard_limits USING btree (account_id);


--
-- Name: ix_risk_tacticals_account_id; Type: INDEX; Schema: public; Owner: zarmor
--

CREATE UNIQUE INDEX ix_risk_tacticals_account_id ON public.risk_tacticals USING btree (account_id);


--
-- Name: ix_session_history_account_id; Type: INDEX; Schema: public; Owner: zarmor
--

CREATE INDEX ix_session_history_account_id ON public.session_history USING btree (account_id);


--
-- Name: ix_system_states_account_id; Type: INDEX; Schema: public; Owner: zarmor
--

CREATE UNIQUE INDEX ix_system_states_account_id ON public.system_states USING btree (account_id);


--
-- Name: ix_telegram_configs_account_id; Type: INDEX; Schema: public; Owner: zarmor
--

CREATE UNIQUE INDEX ix_telegram_configs_account_id ON public.telegram_configs USING btree (account_id);


--
-- Name: ix_trade_history_account_id; Type: INDEX; Schema: public; Owner: zarmor
--

CREATE INDEX ix_trade_history_account_id ON public.trade_history USING btree (account_id);


--
-- Name: ix_trading_accounts_account_id; Type: INDEX; Schema: public; Owner: zarmor
--

CREATE UNIQUE INDEX ix_trading_accounts_account_id ON public.trading_accounts USING btree (account_id);


--
-- Name: uq_license_key; Type: INDEX; Schema: public; Owner: zarmor
--

CREATE UNIQUE INDEX uq_license_key ON public.license_keys USING btree (license_key) WHERE (license_key IS NOT NULL);


--
-- PostgreSQL database dump complete
--

\unrestrict l7zj4iievlKCzc7c1QQebO3nty41eDiBQgzblHOJjWOYLKomUppmDSvcO62bXvG

