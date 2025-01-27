from .config_utils import load_config, save_config

def save_credentials(window):
    """Save credentials to config if 'Remember Password' is checked."""
    config = load_config()
    config['username'] = window.username_input.text() if window.remember_cb.isChecked() else ''
    config['password'] = window.password_input.text() if window.remember_cb.isChecked() else ''
    config['remember'] = window.remember_cb.isChecked()
    save_config(config)
