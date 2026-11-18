"""Prepare and validate single-question exchanges through Codex's approved DSH tool."""
import argparse
import hashlib
import json
from pathlib import Path

REPORTS = Path(__file__).resolve().parents[1] / 'reports'


def make_request(inspection):
    q = inspection.get('question')
    if not isinstance(q, dict) or not str(q.get('text', '')).strip():
        raise ValueError('没有读取到题干，请先运行课程与单题检查。')
    if q.get('has_images') or q.get('has_math'):
        raise ValueError('题目含图片或公式，当前文本读取可能不完整，请先核对原题。')
    if q.get('type') not in ('single_choice', 'multiple_choice', 'judge'):
        raise ValueError('当前仅支持单选、多选、判断题。')
    options = q.get('options', [])
    if len(options) < 2 or any(not o.get('label') or not o.get('text') for o in options):
        raise ValueError('题目选项不完整。')
    labels = [o['label'] for o in options]
    if len(set(labels)) != len(labels):
        raise ValueError('题目选项标签重复。')
    question = {key: q[key] for key in ('type', 'text', 'options')}
    fingerprint = hashlib.sha256(json.dumps(question, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {'question_id': fingerprint, 'question': question}


def validate_response(request, response):
    if not isinstance(response, dict) or response.get('question_id') != request['question_id']:
        raise ValueError('返回答案与当前请求题目不匹配。')
    answer = response.get('answer')
    labels = {o['label'] for o in request['question']['options']}
    if (not isinstance(answer, list) or not answer or
            any(not isinstance(a, str) or a not in labels for a in answer) or
            len(set(answer)) != len(answer)):
        raise ValueError('返回答案必须是合法且不重复的选项标签列表。')
    if request['question']['type'] != 'multiple_choice' and len(answer) != 1:
        raise ValueError('单选或判断题只能返回一个选项。')
    if not isinstance(response.get('explanation'), str) or not response['explanation'].strip():
        raise ValueError('返回结果缺少解析。')
    if type(response.get('needs_review')) is not bool:
        raise ValueError('返回结果缺少有效的核对标记。')
    return {key: response[key] for key in ('question_id','answer','explanation','needs_review')}


def main():
    parser = argparse.ArgumentParser(description='通过 Codex 受审批 DSH 工具进行单题解析')
    parser.add_argument('action', choices=('prepare','import'))
    parser.add_argument('--reports', type=Path, default=REPORTS)
    args = parser.parse_args()
    directory = args.reports
    directory.mkdir(parents=True, exist_ok=True)
    inspection = json.loads((directory / 'course_inspection.json').read_text(encoding='utf-8-sig'))
    current = make_request(inspection)
    request_file = directory / 'dsh_request.json'
    if args.action == 'prepare':
        request_file.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding='utf-8')
        print('DSH 请求已生成。请在 Codex 中通过受审批 DSH 工具调用，输出到 reports/dsh_response.json。')
    else:
        request = json.loads(request_file.read_text(encoding='utf-8-sig'))
        if request != current:
            raise ValueError('题目读取结果已变化，请重新生成请求。')
        response = validate_response(request, json.loads((directory / 'dsh_response.json').read_text(encoding='utf-8-sig')))
        question = request['question']
        lines = ['# DSH 单题解析', '', question['text'], '']
        lines += [f"- {o['label']}：{o['text']}" for o in question['options']]
        lines += ['', '建议答案：' + '、'.join(response['answer']), '', response['explanation'], '',
                  '需要进一步核对：' + ('是' if response['needs_review'] else '模型未标记；仍需人工核对'), '',
                  '来源：本地 DSH，经 Codex 受审批工具调用。未填写或提交网页。']
        (directory / 'DSH单题解析.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
        print('答案格式和题目匹配校验通过，解析已保存。此校验不证明答案正确。')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as exc:
        raise SystemExit(str(exc))
