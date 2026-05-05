from flask import Flask, redirect, url_for, g
from config import Config
from db import close_db
from utils import get_current_user


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    app.teardown_appcontext(close_db)

    # Make Flask's g available in all Jinja2 templates
    app.jinja_env.globals["g"] = g

    from routes.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix="/")

    from routes.workspaces import workspaces_bp
    app.register_blueprint(workspaces_bp)

    from routes.users import users_bp
    app.register_blueprint(users_bp)

    from routes.channels import channels_bp
    app.register_blueprint(channels_bp)

    # from routes.invitations import invitations_bp
    # app.register_blueprint(invitations_bp)

    # from routes.search import search_bp
    # app.register_blueprint(search_bp)

    # from routes.profile import profile_bp
    # app.register_blueprint(profile_bp)

    @app.before_request
    def load_current_user():
        g.current_user = get_current_user()

    @app.route("/")
    def index():
        return redirect(url_for("auth.login"))

    return app
