import base64
import json

from aiohttp import web

from clients import TorrentNotFoundException
from models import Realm, DB
from utils import JsonResponse, jsonify_exceptions


class AlcazarAPI:
    def __init__(self, config, orchestrator):
        self.config = config
        self.orchestrator = orchestrator

        self.app = web.Application()
        self.app.add_routes([
            web.get('/', self.index),
            web.get('/ping', self.ping),
            web.get('/config', self.get_config),
            web.put('/config', self.put_config),
            web.get('/clients', self.get_clients),
            web.post('/clients', self.post_clients),
            web.get('/clients/{client_name}/debug', self.get_client_debug),
            web.post('/torrents/{realm_name}', self.post_torrents),
            web.delete('/torrents/{realm_name}/{info_hash}', self.delete_torrent),
            web.post('/pop_updates', self.post_pop_updates),
        ])

    @jsonify_exceptions
    async def index(self, request):
        return web.Response(text=json.dumps({'hello': 'world'}), content_type='application/json')

    @jsonify_exceptions
    async def ping(self, request):
        return JsonResponse({'success': True})

    @jsonify_exceptions
    async def get_config(self, request):
        return JsonResponse(self.config.to_dict())

    @jsonify_exceptions
    @DB.atomic()
    async def put_config(self, request):
        data = await request.json()
        self.config.update_from_dict(data)
        self.config.save()
        return JsonResponse(self.config.to_dict())

    @jsonify_exceptions
    async def get_clients(self, request):
        return JsonResponse({
            'clients': [client.get_info_dict() for client in self.orchestrator.managers.values()]
        })

    @jsonify_exceptions
    @DB.atomic()
    async def post_clients(self, request):
        data = await request.json()
        realm = Realm.select().where(Realm.name == data['realm']).first()
        if not realm:
            realm = Realm.create(name=data['realm'])
        instance = self.orchestrator.add_instance(
            realm=realm,
            instance_type=data['instance_type'],
        )
        return JsonResponse(instance.get_info_dict())

    @jsonify_exceptions
    async def get_client_debug(self, request):
        manager = self.orchestrator.managers.get(request.match_info['client_name'])
        if not manager:
            return JsonResponse({'detail': 'Manager not found'}, status=404)
        return JsonResponse(manager.get_debug_dict(), compact=False)

    @jsonify_exceptions
    async def post_torrents(self, request):
        data = await request.json()
        realm = Realm.select().where(Realm.name == request.match_info['realm_name']).first()
        if not realm:
            return JsonResponse({'detail': 'Realm does not exist. Create it by adding a client to it.'}, status=400)

        torrent = await self.orchestrator.add_torrent(
            realm=realm,
            torrent=base64.b64decode(data['torrent']),
            download_path=data['download_path'],
        )
        return JsonResponse(torrent.to_dict())

    @jsonify_exceptions
    async def delete_torrent(self, request):
        realm = Realm.select().where(Realm.name == request.match_info['realm_name']).first()
        if not realm:
            return JsonResponse({'detail': 'Realm does not exist. Create it by adding a client to it.'}, status=400)

        try:
            await self.orchestrator.delete_torrent(
                realm=realm,
                info_hash=request.match_info['info_hash'],
            )
            return JsonResponse({})
        except TorrentNotFoundException:
            return JsonResponse({'detail': 'Torrent not found.'}, status=404)

    @jsonify_exceptions
    async def post_pop_updates(self, request):
        max_updates = request.query.get('max_updates', 10000)
        # TODO: Implement max_updates
        updated_dicts = list(self.orchestrator.pooled_updates.values())
        removed_hashes = list(self.orchestrator.pooled_removes)
        self.orchestrator.clear_pooled_events()
        return JsonResponse({
            'updated': updated_dicts,
            'removed': removed_hashes,
        })

    def run(self):
        web.run_app(self.app, port=self.config.api_port)
