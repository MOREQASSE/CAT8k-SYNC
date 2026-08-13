from jinja2 import Environment, FileSystemLoader
import os

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "config", "templates")
TEMPLATE_MAP = {
    "add_branch": "add_branch.j2",
    "add_subdept": "add_subdept.j2",
    "add_endpoint": "add_endpoint.j2",
}


def load_template(action):
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    template_file = TEMPLATE_MAP.get(action)
    if not template_file:
        raise ValueError(f"Unknown action: {action}. Valid: {list(TEMPLATE_MAP.keys())}")
    return env.get_template(template_file)


def render_config(action, variables):
    template = load_template(action)
    return template.render(**variables)
