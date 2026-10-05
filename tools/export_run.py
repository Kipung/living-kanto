#!/usr/bin/env python3
"""Export one coherently backed-up committed save without inference or writes to it."""
import argparse
import json
from pathlib import Path
from summarize_behavior import coherent_store


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True)
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    database=Path(args.database)
    if not database.is_file():parser.error('Database must already exist')
    with coherent_store(database) as (store,interval):
        metadata,state,head=store.load_run(args.run_id)
        replay=store.replay(args.run_id)
        if replay.state_hash!=state.state_hash:raise RuntimeError('Replay disagrees with saved state')
        public_metadata=metadata.to_dict();public_metadata['data_directory']=''
        bundle={'format':'living-kanto-run-v1','metadata':public_metadata,
                'genesis':store.load_genesis(args.run_id).to_dict(),
                'events':[event.to_dict() for event in store.iter_events(args.run_id)],
                'inference_settings_included':False,'state_hash':state.state_hash,'head_hash':head}
        output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
        temporary=output.with_suffix(output.suffix+'.tmp')
        temporary.write_text(json.dumps(bundle,separators=(',',':'))+'\n');temporary.replace(output)
        print(json.dumps({'output':str(output),'state_version':state.state_version,
                          'state_hash':state.state_hash,'head_hash':head,
                          'replay_verified':True,'snapshot_interval':interval,
                          'inference_calls':0,'original_database_modified':False}))


if __name__=='__main__':main()
