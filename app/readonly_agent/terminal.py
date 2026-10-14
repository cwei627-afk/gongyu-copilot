"""Extract the terminal turn from official strategy records, not text braces."""
import json
import re


def terminal_payload(capability, agent_log):
    try:
        if not isinstance(agent_log, list): raise ValueError('log shape')
        rounds = [item for item in agent_log if isinstance(item, dict)
                  and isinstance(item.get('label'), str) and item['label'].startswith('ROUND ')]
        if not 1 <= len(rounds) <= 6 or [item['label'] for item in rounds] != [f'ROUND {i+1}' for i in range(len(rounds))]:
            raise ValueError('missing/duplicate/out-of-order round')
        if any(item.get('node_id') != 'readonly_agent' or item.get('parent_id') is not None
               or item.get('status') != 'success' or item.get('error') is not None for item in rounds):
            raise ValueError('untrusted execution record')
        final = rounds[-1]['data']['output']
        if final['tool_responses'] != [] or not isinstance(final['llm_response'], str):
            raise ValueError('no terminal model turn')
        return {'payload': json.dumps({'capability': capability, 'text': final['llm_response']}, ensure_ascii=False)}
    except (ValueError, KeyError, TypeError):
        return {'payload': json.dumps({'capability': capability, 'text': '{}', 'execution_failed': True})}
