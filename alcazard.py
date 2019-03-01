#!/usr/bin/env python3
import argparse
import logging

from host import AlcazarHost


def configure_logging(log_level):
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )

    peewee_logger = logging.getLogger('peewee')
    peewee_logger.setLevel(max(logging.INFO, log_level))  # We don't want peewee queries


def run_config(args):
    server = AlcazarHost(args.state)
    server.config(args.api_port)


def run_main(args):
    server = AlcazarHost(args.state)
    server.run()


def main():
    parser = argparse.ArgumentParser(description='Alcazard torrent client.')
    parser.add_argument('--log-level', default='INFO', choices=[
        'CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'], help='Logging level.')
    parser.add_argument('--state', required=True, help='Path to config and state directory.')

    subparsers = parser.add_subparsers(help='sub-command help')

    parser_config = subparsers.add_parser('config')
    parser_config.set_defaults(func=run_config)
    parser_config.add_argument('--api-port', help='Port to listen on for the API.')

    parser_run = subparsers.add_parser('run')
    parser_run.set_defaults(func=run_main)

    args = parser.parse_args()
    configure_logging(logging.getLevelName(args.log_level))  # getLevelName will return the code here
    args.func(args)


if __name__ == '__main__':
    main()
