"""Install / uninstall lifecycle hooks (serverkit-mail extension).

Contract (per the plugin SDK): a single positional arg — the InstalledPlugin
row. ``on_uninstall`` also accepts a ``purge`` flag. Everything here is wrapped
so a hook failure never blocks install/uninstall.
"""
import logging

logger = logging.getLogger(__name__)


def on_install(plugin):
    """Register the extension's notification events. Best-effort."""
    try:
        from app.plugins_sdk import notify
        notify.register_event(
            'mail.preflight_failed',
            'Mail deliverability preflight failed',
            template='generic', severity='warning', category='system')
        notify.register_event(
            'mail.dns_deployed',
            'Mail DNS records deployed',
            template='generic', severity='success', category='system')
        logger.info('serverkit-mail installed: notification events registered')
    except Exception as e:  # noqa: BLE001
        logger.warning('serverkit-mail on_install hook error: %s', e)


def on_uninstall(plugin, purge=False):
    """Best-effort stop/remove the Stalwart container on uninstall.

    On ``purge`` the mail data directory is deleted too; otherwise the container
    is removed but the data is kept so a reinstall can pick it back up.
    """
    try:
        from .stalwart_service import StalwartService
        if StalwartService.is_installed():
            result = StalwartService.uninstall(keep_data=not purge)
            logger.info('serverkit-mail on_uninstall: %s', result)
        else:
            logger.info('serverkit-mail on_uninstall: container not present')
    except Exception as e:  # noqa: BLE001
        logger.warning('serverkit-mail on_uninstall hook error: %s', e)
