import keyring

def load_credentials(window, service_name, username_key, password_key):
    """Load stored credentials from keyring."""
    saved_username = keyring.get_password(service_name, username_key)
    saved_password = keyring.get_password(service_name, password_key)
    if saved_username:
        window.username_input.setText(saved_username)
    if saved_password:
        window.password_input.setText(saved_password)
        window.remember_cb.setChecked(True)

def save_credentials(window, service_name, username_key, password_key):
    """Save credentials to keyring if 'Remember Password' is checked."""
    username = window.username_input.text()
    password = window.password_input.text()

    if window.remember_cb.isChecked():
        keyring.set_password(service_name, username_key, username)
        keyring.set_password(service_name, password_key, password)
    else:
        keyring.delete_password(service_name, username_key)
        keyring.delete_password(service_name, password_key)
