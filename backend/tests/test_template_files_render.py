"""Template ``files:`` rendering: absolute container paths are bind-mounted,
relative paths (build-context files like ``Dockerfile``) are only written
into the app directory.

Regression test: a relative ``path: Dockerfile`` used to produce the invalid
volume spec ``./Dockerfile:Dockerfile`` and every compose-based install of
such a template failed at ``docker compose up`` with "invalid mount config
for type bind: mount path must be absolute".
"""
import yaml

from app.services.template_service import TemplateService as TS


def _render(files):
    template = {
        'compose': {
            'services': {'app': {'image': 'example:latest', 'volumes': ['data:/data']}},
            'volumes': {'data': None},
        },
        'files': files,
    }
    return TS._render_compose_and_files(template, {}, '/tmp/app-x')


def test_absolute_file_path_is_bind_mounted():
    result = _render([{'path': '/app/config.yaml', 'content': 'a: b'}])

    assert result['success']
    compose = yaml.safe_load(result['compose_content'])
    volumes = compose['services']['app']['volumes']
    assert './config.yaml:/app/config.yaml' in volumes
    assert result['files'][0]['path'].endswith('config.yaml')


def test_relative_file_path_is_written_but_not_mounted():
    result = _render([{'path': 'Dockerfile', 'content': 'FROM scratch'}])

    assert result['success']
    # Still written into the app directory (build context).
    assert result['files'][0]['path'].endswith('Dockerfile')
    # ...but NOT bind-mounted into the container.
    compose = yaml.safe_load(result['compose_content'])
    volumes = compose['services']['app']['volumes']
    assert volumes == ['data:/data']
    assert not any('Dockerfile' in str(v) for v in volumes)
