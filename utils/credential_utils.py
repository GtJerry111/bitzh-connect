from .config_utils import load_config, save_config

def save_credentials(self):
    config = load_config()  # Load existing config first
    
    if self.remember_cb.isChecked():
        config['username'] = self.username_input.text()
        config['password'] = self.password_input.text()
        config['remember'] = True
    else:
        config['username'] = ''
        config['password'] = ''
        config['remember'] = False
    
    save_config(config)  # Save the updated config
