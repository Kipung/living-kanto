"""Private conditional thoughts; never execute actions or replace live tasks."""
import copy
from ..contracts import LegalAction
from ..contracts.base import content_hash
from .engine import EngineError, StaleActionError


def context_token(state, hid):
    h = state.humans[hid]
    # Walking progress/elapsed needs/completion are allowed; new choices,
    # delivered speech, battles or changed resources supersede a thought.
    return content_hash({'facts': {k: h.get(k) for k in ('goal', 'goals', 'memories', 'last_decision',
        'party', 'box', 'inventory', 'money', 'badges', 'battle_id')},
        'purpose': {k: (h.get('individual_life') or {}).get(k) for k in ('aspiration', 'commitment')},
        'pokemon': {pid: state.pokemon.get(pid) for pid in h.get('party', [])}})


def capture(engine, state, hid):
    obs = engine.observation_for(state, hid)
    detached = state.apply_changes([{'op': 'set', 'path': f'humans.{hid}.{key}', 'value': value}
        for key, value in (('movement_intent', None), ('activity', None), ('ready_at', state.simulated_time))])
    from .task_continuity import options
    plans = [a for a in options(detached.humans[hid], engine.legal_actions(detached, hid)) if a.action == 'plan_next_step']
    obs.legal_actions = tuple(plans + [LegalAction(action='remember', arguments={'text': '<non-empty text, <=200 chars>'},
        known_consequences={'background_reflection_only': True, 'does_not_execute_action': True})])
    obs.self_state['cognitive_mode'] = 'background_deliberation'
    obs.self_state['ongoing_movement'] = copy.deepcopy({k: v for k, v in (state.humans[hid].get('movement_intent') or {}).items()
        if k in ('action', 'arguments', 'accepted_at')})
    obs.self_state['cognition_instruction'] = ('Think about a useful next step or reflect on your purpose while the accepted activity continues. '
        'Plans are conditional suggestions from your current position. This response cannot act, stop movement, speak, or replace a task. '
        'Use remember for subjective reflection. Never describe a proposed result as accomplished.')
    obs.validate()
    return obs, context_token(state, hid)


def validate_choice(choice, observation):
    args = choice.get('arguments', {}); action = choice.get('action')
    if action not in {'remember', 'plan_next_step'} or not any(a.action == action and
        {k: v for k, v in a.arguments.items() if k != 'text'} == {k: v for k, v in args.items() if k != 'text'} for a in observation.legal_actions):
        raise EngineError('Background output must be an offered reflection or conditional plan')
    if not isinstance(args.get('text'), str) or not args['text'].strip() or len(args['text']) > 200:
        raise EngineError('Background thought needs nonempty text of at most 200 characters')


def build_event(engine, store, run_id, hid, choice, observation, token, provenance):
    _, state, head = store.load_run(run_id)
    if token != context_token(state, hid): raise StaleActionError('Background thought superseded by interaction, choice or resources')
    if provenance.get('kind') != 'model' or not provenance.get('model_id'):
        raise EngineError('Background thought requires local model provenance')
    validate_choice(choice, observation)
    args = choice["arguments"]; action = choice["action"]
    thought = {'kind': 'conditional_plan' if action == 'plan_next_step' else 'subjective_reflection',
        'text': args['text'], 'proposed_action': args.get('action'), 'proposed_arguments': copy.deepcopy(args.get('arguments')),
        'decision_explanation': choice['decision_explanation'], 'observed_at': observation.simulated_time,
        'recorded_at': state.simulated_time, 'observation_version': observation.observation_version,
        'suggested_from_location': copy.deepcopy(observation.location),
        'provenance': copy.deepcopy(provenance), 'execution_authorized': False}
    prior = state.humans[hid].get('cognition') or {}
    value = {'latest': thought, 'previous': (prior.get('previous', []) + ([prior['latest']] if prior.get('latest') else []))[-8:]}
    return engine._shared_event(state, head, [{'op': 'set', 'path': f'humans.{hid}.cognition', 'value': value}],
        kind='human.deliberated', causation={'human_id': hid, 'action': action, 'action_arguments': args,
        'decision_explanation': choice['decision_explanation'], 'provenance': provenance, 'cognitive_channel': 'deliberation'})


def private_view(h):
    latest = copy.deepcopy((h.get('cognition') or {}).get('latest'))
    if latest: latest.pop('provenance', None)
    return {'latest': latest, 'instruction': 'Your earlier subjective thought or conditional suggestion did not act or change your task. '
        'Check present facts and offered actions before using it.'}
