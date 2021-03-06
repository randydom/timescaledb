
setup
{
    SELECT _timescaledb_internal.stop_background_workers();
    CREATE TABLE ts_continuous_test(time INTEGER, location INTEGER);
    SELECT create_hypertable('ts_continuous_test', 'time', chunk_time_interval => 10);
    INSERT INTO ts_continuous_test SELECT i, i FROM
        (SELECT generate_series(0, 29) AS i) AS i;
    CREATE VIEW continuous_view
        WITH ( timescaledb.continuous, timescaledb.refresh_interval='72 hours')
        AS SELECT time_bucket('5', time), COUNT(location)
            FROM ts_continuous_test
            GROUP BY 1;
}

teardown {
    DROP TABLE ts_continuous_test CASCADE;
}

session "I"
step "Ib"	{ BEGIN; SET LOCAL lock_timeout = '50ms'; SET LOCAL deadlock_timeout = '10ms';}
step "I1"	{ INSERT INTO ts_continuous_test VALUES (1, 1); }
step "Ic"	{ COMMIT; }

session "Ip"
step "Ipb"	{ BEGIN; SET LOCAL lock_timeout = '50ms'; SET LOCAL deadlock_timeout = '10ms';}
step "Ip1"	{ INSERT INTO ts_continuous_test VALUES (29, 29); }
step "Ipc"	{ COMMIT; }

session "S"
step "Sb"	{ BEGIN; SET LOCAL lock_timeout = '50ms'; SET LOCAL deadlock_timeout = '10ms';}
step "S1"	{ SELECT count(*) FROM ts_continuous_test; }
step "Sc"	{ COMMIT; }

session "R"
step "Refresh"	{ REFRESH MATERIALIZED VIEW continuous_view; }

session "R2"
setup { SET lock_timeout = '50ms'; SET deadlock_timeout = '10ms';  }
step "Refresh2"	{ REFRESH MATERIALIZED VIEW continuous_view; }
teardown { SET lock_timeout TO default; SET deadlock_timeout to default; }

# the invalidation log is grabbed in the second materialization tranasction
# not the first, so it serves as a good sequencing point
session "L"
step "LockInval" { BEGIN; LOCK TABLE _timescaledb_catalog.continuous_aggs_hypertable_invalidation_log; }
step "UnlockInval" { ROLLBACK; }

#the completed threshold will block the REFRESH but not the INSERT
session "LC"
step "LockCompleted" { BEGIN; LOCK TABLE _timescaledb_catalog.continuous_aggs_completed_threshold; }
step "UnlockCompleted" { ROLLBACK; }

#only one rereshe
permutation "LockInval" "Refresh2" "Refresh"  "UnlockInval"

#refresh and insert/select do not block each other
permutation "Ib" "LockCompleted" "I1" "Refresh" "Ic" "UnlockCompleted"
permutation "Ib" "LockCompleted" "Refresh" "I1" "Ic" "UnlockCompleted"
permutation "Sb" "LockInval" "Refresh" "S1" "Sc" "UnlockInval"
permutation "Sb" "LockInval" "S1" "Refresh" "Sc" "UnlockInval"

#insert will see new invalidations (you can tell since they are waiting on the invalidation log lock)
permutation "Ib" "LockInval" "Refresh" "I1" "Ic" "UnlockInval"
permutation "Ib" "LockInval" "I1" "Refresh" "Ic" "UnlockInval"

#with no invalidation threshold, inserts will not write to the invalidation log
permutation "Ib" "LockInval" "I1" "Ic" "Refresh" "UnlockInval"

#inserts beyond the invalidation will not write to the log
permutation "Ipb" "LockInval" "Refresh" "Ip1" "Ipc" "UnlockInval"
permutation "Ipb" "LockInval" "Ip1" "Refresh" "Ipc" "UnlockInval"
permutation "Ipb" "LockInval" "Ip1" "Ipc" "Refresh" "UnlockInval"


#refresh and insert/select do not block each other
permutation "I1" "Refresh" "LockInval" "Refresh" "Ib" "I1" "Ic" "UnlockInval"
permutation "I1" "Refresh" "LockInval" "Ib" "I1" "Refresh" "Ic" "UnlockInval"
permutation "I1" "Refresh" "LockInval" "Refresh" "Sb" "S1" "Sc" "UnlockInval"
permutation "I1" "Refresh" "LockInval" "Sb" "S1" "Refresh" "Sc" "UnlockInval"
