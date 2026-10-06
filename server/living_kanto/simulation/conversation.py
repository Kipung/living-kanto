"""Private delivery ledger; canonical source_state_version is the pre-event boundary.

Only recorded delivery establishes receipt; no automatic responses or legacy
reconstruction. Strictly greater boundaries establish later utterances only.
"""
import copy


def next_memory_slot(memories):
    """Append after the highest numeric slot; preserve sparse and named history."""
    numeric = [int(str(slot)) for slot in memories if str(slot).isdigit()]
    return str(max(numeric, default=-1) + 1)


def conversation_view(h):
    """Recorded delivery and own speech only; no inferred answers or retrodelivery.

    A later utterance to the same person establishes temporal follow-up, not
    that it answers the question or that either person's claim is true.
    """
    memories = list((h.get('memories') or {}).items())
    received = [(slot, m) for slot, m in memories if isinstance(m, dict)
                and m.get('kind') == 'heard_speech' and m.get('direction') == 'heard'
                and m.get('source') == 'recorded_speech']
    spoken = [m for _, m in memories if isinstance(m, dict) and m.get('direction') == 'spoken'
              and m.get('source') == 'recorded_speech']
    choices = [r for r in (h.get('individual_life') or {}).get('recent_decisions', [])
               if r.get('action') in {'talk_to','respond_to'}]
    sent = [{'text': r.get('arguments', {}).get('text'),
             'other': r.get('arguments', {}).get('human_id'), 'time': r.get('at'),
             'source_state_version': r.get('source_state_version'), 'source': 'accepted_own_choice'}
            for r in choices]
    def followup(message, candidates):
        boundary = message.get('source_state_version')
        if type(boundary) is not int:
            return None
        related = [m for m in candidates if m.get('other') == message.get('other')]
        if any(type(m.get('source_state_version')) is int and m['source_state_version'] > boundary for m in related):
            return True
        if any(type(m.get('source_state_version')) is not int for m in related):
            return None
        return False
    def order(row):
        slot, m = row
        version = m.get('source_state_version')
        return (version if type(version) is int else -1, str(slot))
    recent_received = []
    for slot, m in sorted(received, key=order)[-4:]:
        row = {key: copy.deepcopy(m[key]) for key in
               ('text', 'other', 'speaker_name', 'time', 'speech_id', 'source_state_version', 'reply_to', 'response_disposition', 'semantic_answer_verified') if key in m}
        row['source_memory_id'] = str(slot)
        replies = [x for x in spoken if x.get('reply_to') == m.get('speech_id')]
        row['explicit_reply_recorded'] = bool(replies)
        row['reply_dispositions'] = [x.get('response_disposition') for x in replies][-2:]
        row['response_recorded_after_message'] = followup(m, spoken + sent)
        recent_received.append(row)
    recent_sent = []
    incoming = [m for _, m in received]
    for m in sent[-4:]:
        row = copy.deepcopy(m)
        row['speech_recorded_after_message'] = followup(m, incoming)
        recent_sent.append(row)
    return {'recent_received': recent_received, 'recent_sent': recent_sent,
            'legacy_received_messages_reconstructed': False,
            'notice': 'Received entries prove speech was delivered, not that its content is true. A later speech marker proves only another utterance to the same person, not a relevant answer. Missing ordering is unknown; lists are bounded and may omit earlier speech.'}


def reply_options(h, offered):
    from ..contracts import LegalAction
    nearby = {a.arguments['human_id'] for a in offered if a.action == 'talk_to'}
    memories = [m for m in (h.get('memories') or {}).values() if isinstance(m, dict)]
    replied = {m.get('reply_to') for m in memories if m.get('direction') == 'spoken'}
    received = [m for m in memories if m.get('direction') == 'heard' and m.get('source') == 'recorded_speech'
                and m.get('speech_id') and m.get('speech_id') not in replied and m.get('other') in nearby]
    received.sort(key=lambda m: m.get('source_state_version', -1))
    return [LegalAction(action='respond_to', arguments={'human_id': m['other'], 'speech_id': m['speech_id'],
            'disposition': disposition, 'text': '<message, <=200 chars>'}, known_consequences={
            'duration_seconds': 30, 'received_message': m['text'], 'records_reply_to': m['speech_id'],
            'semantic_answer_verified': False}) for m in received[-2:] for disposition in ('answer', 'acknowledge', 'decline')]


def validate_reply(h, args, legal):
    from .engine import EngineError
    if set(args) != {'human_id', 'speech_id', 'disposition', 'text'} or not any(
            all(a.arguments.get(k) == args[k] for k in ('human_id', 'speech_id', 'disposition')) for a in legal):
        raise EngineError('Reply must address a currently offered privately received message')
