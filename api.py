import asyncio
import base64
import json

from aiohttp import web

from clients import TorrentNotFoundException, TorrentAlreadyAddedException
from models import Realm, DB
from orchestrator import NoManagerForRealmException, NotInitializedException
from utils import JsonResponse, jsonify_exceptions


class AlcazarAPI:
    def __init__(self, config, orchestrator):
        self.config = config
        self.orchestrator = orchestrator

        self.app = web.Application(
            client_max_size=16 * 1024 * 1024,  # 16MB max request size
        )
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
            web.post('/pop_update_batch', self.post_pop_update_batch),
            web.get('/torrents/force_recheck/{realm_name}/{info_hash}', self.force_recheck),
            web.get('/torrents/pause_torrent/{realm_name}/{info_hash}', self.pause_torrent),
            web.get('/torrents/resume_torrent/{realm_name}/{info_hash}', self.resume_torrent),
            web.post('/torrents/rename_torrent/{realm_name}/{info_hash}', self.rename_torrent),
            web.get('/torrents/force_reannounce/{realm_name}/{info_hash}', self.force_reannounce),
            web.post('/torrents/move_data/{realm_name}/{info_hash}', self.move_data),
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
    async def put_config(self, request):
        data = await request.json()
        with DB.atomic():
            self.config.update_from_dict(data)
            self.config.save()
        return JsonResponse(self.config.to_dict())

    @jsonify_exceptions
    async def get_clients(self, request):
        manager_data = []
        for managers in self.orchestrator.managers_by_realm.values():
            for manager in managers:
                manager_data.append(manager.get_info_dict())

        return JsonResponse({
            'clients': manager_data,
        })

    @jsonify_exceptions
    async def post_clients(self, request):
        data = await request.json()
        with DB.atomic():
            realm = Realm.select().where(Realm.name == data['realm']).first()
            if not realm:
                realm = Realm.create(name=data['realm'])
            try:
                instance = self.orchestrator.add_instance(
                    realm=realm,
                    instance_type=data['instance_type'],
                    config_kwargs=data.get('config', {}),
                )
            except asyncio.TimeoutError:
                return JsonResponse(
                    data={'detail': 'Alcazar is busy performing another action. Try again later.'},
                    status=503,
                )
        return JsonResponse(instance.get_info_dict())

    @jsonify_exceptions
    async def get_client_debug(self, request):
        name = request.match_info['client_name']
        manager = None
        for managers in self.orchestrator.managers_by_realm.values():
            for realm_manager in managers:
                if realm_manager.name == name:
                    manager = realm_manager
        if not manager:
            return JsonResponse({'detail': 'Manager not found'}, status=404)
        return JsonResponse(manager.get_debug_dict(), compact=False)

    @jsonify_exceptions
    async def post_torrents(self, request):
        data = await request.json()
        realm = Realm.select().where(Realm.name == request.match_info['realm_name']).first()
        if not realm:
            return JsonResponse({'detail': 'Realm does not exist. Create it by adding a client to it.'}, status=400)

        try:
            data = await self.orchestrator.add_torrent(
                realm=realm,
                torrent_file=base64.b64decode(data['torrent']),
                download_path=data['download_path'],
                name=data.get('name'),
            )
        except (NotInitializedException, NoManagerForRealmException) as exc:
            return JsonResponse({'detail': str(exc)}, status=400)
        except TorrentAlreadyAddedException as exc:
            return JsonResponse({'detail': str(exc)}, status=409)
        except asyncio.TimeoutError:
            return JsonResponse({'detail': 'Alcazar is busy performing another action. Try again later.'}, status=503)
        return JsonResponse(data)

    @jsonify_exceptions
    async def delete_torrent(self, request):
        realm = Realm.select().where(Realm.name == request.match_info['realm_name']).first()
        if not realm:
            return JsonResponse({'detail': 'Realm does not exist. Create it by adding a client to it.'}, status=400)

        try:
            await self.orchestrator.remove_torrent(
                realm=realm,
                info_hash=request.match_info['info_hash'],
            )
            return JsonResponse({})
        except TorrentNotFoundException:
            return JsonResponse({'detail': 'Torrent not found.'}, status=404)
        except asyncio.TimeoutError:
            return JsonResponse({'detail': 'Alcazar is busy performing another action. Try again later.'}, status=503)

    @jsonify_exceptions
    async def post_pop_update_batch(self, request):
        limit = int(request.query.get('limit', '10000'))
        realm_batches = self.orchestrator.pop_update_batch_dicts(limit)
        return JsonResponse(realm_batches)

    @jsonify_exceptions
    async def pause_torrent(self, request):
        realm = Realm.select().where(Realm.name == request.match_info['realm_name']).first()
        if not realm:
            return JsonResponse({'detail': 'Realm does not exist. Create it by adding a client to it.'}, status=400)

        try:
            await self.orchestrator.pause_torrent(
                realm=realm,
                info_hash=request.match_info['info_hash']
            )
            return JsonResponse({})
        except TorrentNotFoundException:
            return JsonResponse({'detail': 'Torrent not found.'}, status=404)
        except asyncio.TimeoutError:
            return JsonResponse({'detail': 'Alcazar is busy performing another action. Try again later.'}, status=503)

    @jsonify_exceptions
    async def resume_torrent(self, request):
        realm = Realm.select().where(Realm.name == request.match_info['realm_name']).first()
        if not realm:
            return JsonResponse({'detail': 'Realm does not exist. Create it by adding a client to it.'}, status=400)

        try:
            await self.orchestrator.resume_torrent(
                realm=realm,
                info_hash=request.match_info['info_hash']
            )
            return JsonResponse({})
        except TorrentNotFoundException:
            return JsonResponse({'detail': 'Torrent not found.'}, status=404)
        except asyncio.TimeoutError:
            return JsonResponse({'detail': 'Alcazar is busy performing another action. Try again later.'}, status=503)

    @jsonify_exceptions
    async def rename_torrent(self, request):
        data = await request.json()
        realm = Realm.select().where(Realm.name == request.match_info['realm_name']).first()
        if not realm:
            return JsonResponse({'detail': 'Realm does not exist. Create it by adding a client to it.'}, status=400)

        try:
            await self.orchestrator.rename_torrent(
                realm=realm,
                info_hash=request.match_info['info_hash'],
                name=data['name']
            )
            return JsonResponse({})
        except TorrentNotFoundException:
            return JsonResponse({'detail': 'Torrent not found.'}, status=404)
        except asyncio.TimeoutError:
            return JsonResponse({'detail': 'Alcazar is busy performing another action. Try again later.'}, status=503)
    
    @jsonify_exceptions
    async def force_reannounce(self, request):
        realm = Realm.select().where(Realm.name == request.match_info['realm_name']).first()
        if not realm:
            return JsonResponse({'detail': 'Realm does not exist. Create it by adding a client to it.'}, status=400)

        try:
            await self.orchestrator.force_reannounce(
                realm=realm,
                info_hash=request.match_info['info_hash']
            )
            return JsonResponse({})
        except TorrentNotFoundException:
            return JsonResponse({'detail': 'Torrent not found.'}, status=404)
        except asyncio.TimeoutError:
            return JsonResponse({'detail': 'Alcazar is busy performing another action. Try again later.'}, status=503)
    
    @jsonify_exceptions
    async def force_recheck(self, request):
        realm = Realm.select().where(Realm.name == request.match_info['realm_name']).first()
        if not realm:
            return JsonResponse({'detail': 'Realm does not exist. Create it by adding a client to it.'}, status=400)

        try:
            await self.orchestrator.force_recheck(
                realm=realm,
                info_hash=request.match_info['info_hash']
            )
            return JsonResponse({})
        except TorrentNotFoundException:
            return JsonResponse({'detail': 'Torrent not found.'}, status=404)
        except asyncio.TimeoutError:
            return JsonResponse({'detail': 'Alcazar is busy performing another action. Try again later.'}, status=503)
    
    @jsonify_exceptions
    async def move_data(self, request):
        data = await request.json()
        realm = Realm.select().where(Realm.name == request.match_info['realm_name']).first()
        if not realm:
            return JsonResponse({'detail': 'Realm does not exist. Create it by adding a client to it.'}, status=400)

        try:
            await self.orchestrator.move_data(
                realm=realm,
                info_hash=request.match_info['info_hash'],
                download_path=data['download_path']
            )
            return JsonResponse({})
        except TorrentNotFoundException:
            return JsonResponse({'detail': 'Torrent not found.'}, status=404)
        except asyncio.TimeoutError:
            return JsonResponse({'detail': 'Alcazar is busy performing another action. Try again later.'}, status=503)

    def run(self):
        web.run_app(self.app, port=self.config.api_port)
