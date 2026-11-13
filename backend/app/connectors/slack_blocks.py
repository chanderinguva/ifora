"""Bounded, display-only Block Kit. Template values can change text, never JSON structure."""
import json

MAX_BYTES = 16000


def validate_blocks(value):
    if isinstance(value, str):
        if len(value.encode()) > MAX_BYTES:
            raise ValueError('Slack blocks exceed 16000 bytes')
        try:
            value = json.loads(value)
        except (ValueError, RecursionError):
            raise ValueError('Slack blocks must be a JSON array') from None
    if not isinstance(value, list) or not 1 <= len(value) <= 50:
        raise ValueError('Use between 1 and 50 Slack blocks')

    def text(obj, limit, plain=False):
        if not isinstance(obj, dict) or set(obj) - {'type', 'text', 'emoji', 'verbatim'}:
            raise ValueError('Unsupported Slack text object')
        if obj.get('type') not in (['plain_text'] if plain else ['plain_text', 'mrkdwn']):
            raise ValueError('Use plain_text or mrkdwn text')
        if not isinstance(obj.get('text'), str) or not 1 <= len(obj['text']) <= limit:
            raise ValueError(f'Slack text must contain 1 to {limit} characters')
        if any(ord(c) < 32 and c not in '\n\t\r' for c in obj['text']):
            raise ValueError('Slack text contains control characters')
        if 'emoji' in obj and (obj['type'] != 'plain_text' or not isinstance(obj['emoji'], bool)):
            raise ValueError('emoji applies only to plain_text')
        if 'verbatim' in obj and (obj['type'] != 'mrkdwn' or not isinstance(obj['verbatim'], bool)):
            raise ValueError('verbatim applies only to mrkdwn')

    for block in value:
        if not isinstance(block, dict):
            raise ValueError('Each Slack block must be an object')
        kind = block.get('type')
        if not isinstance(kind, str):
            raise ValueError('Each block needs a type')
        allowed = {'header': {'type', 'text'}, 'section': {'type', 'text', 'fields'},
                   'divider': {'type'}, 'context': {'type', 'elements'}}.get(kind)
        if not allowed or set(block) - allowed:
            raise ValueError('Supported blocks: header, section, divider, context (no interactive elements)')
        if kind == 'header':
            text(block.get('text'), 150, True)
        elif kind == 'section':
            if 'text' not in block and 'fields' not in block:
                raise ValueError('A section needs text or fields')
            if 'text' in block:
                text(block['text'], 3000)
            if 'fields' in block:
                fields = block['fields']
                if not isinstance(fields, list) or not 1 <= len(fields) <= 10:
                    raise ValueError('A section supports 1 to 10 fields')
                for item in fields:
                    text(item, 2000)
        elif kind == 'context':
            elements = block.get('elements')
            if not isinstance(elements, list) or not 1 <= len(elements) <= 10:
                raise ValueError('Context supports 1 to 10 text elements')
            for item in elements:
                text(item, 2000)
    try:
        if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_BYTES:
            raise ValueError('Slack blocks exceed 16000 bytes')
    except (TypeError, RecursionError):
        raise ValueError('Invalid Slack blocks') from None
    return value


def render_blocks(value, render):
    blocks = validate_blocks(value)

    def render_text(value):
        result = render(value)
        if result is None:
            return ''
        return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, separators=(',', ':'))

    def walk(obj):
        if isinstance(obj, list):
            return [walk(item) for item in obj]
        if isinstance(obj, dict):
            return {key: (render_text(v) if key == 'text' and isinstance(v, str) else walk(v)) for key, v in obj.items()}
        return obj

    return validate_blocks(walk(blocks))
