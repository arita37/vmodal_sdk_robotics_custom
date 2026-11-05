"""Offline regression coverage for legacy and current SDK upload signatures."""
import asyncio
import errno
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.mcp_server.robot import video_upload


class VideoUploadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / "cam_scene.mp4"
        self.source.write_bytes(b"original frame bytes")

    async def upload(self, method):
        client = SimpleNamespace(collections=SimpleNamespace(video_upload=method))
        return await video_upload(client, str(self.source), "demo", "cam_scene", "ep_demo1")

    async def test_modern_signature_preserves_path_and_disables_resizing(self):
        async def modern(filepath_local, collection_name, sub_collection_name, video_filename, reduce_size=True):
            self.assertEqual(filepath_local, str(self.source))
            self.assertEqual((collection_name, sub_collection_name), ("demo", "cam_scene"))
            self.assertEqual(video_filename, "ep_demo1.mp4")
            self.assertIs(reduce_size, False)
            return "uploaded"
        self.assertEqual(await self.upload(modern), "uploaded")

    async def test_legacy_alias_has_episode_name_original_bytes_and_is_removed(self):
        seen = []
        async def legacy(filepath_local, collection_name, sub_collection_name):
            path = Path(filepath_local)
            seen.append(path)
            self.assertEqual(path.name, "ep_demo1.mp4")
            self.assertEqual(path.read_bytes(), self.source.read_bytes())
            self.assertTrue(path.samefile(self.source))
            await asyncio.sleep(0)
            self.assertTrue(path.exists())
            return "uploaded"
        self.assertEqual(await self.upload(legacy), "uploaded")
        self.assertFalse(seen[0].parent.exists())
        self.assertEqual(self.source.read_bytes(), b"original frame bytes")

    async def test_cross_device_copy_and_reduce_size_only_signature(self):
        seen = []
        async def intermediate(filepath_local, collection_name, sub_collection_name, reduce_size=True):
            path = Path(filepath_local)
            seen.append(path)
            self.assertEqual(path.name, "ep_demo1.mp4")
            self.assertEqual(path.read_bytes(), self.source.read_bytes())
            self.assertFalse(path.samefile(self.source))
            self.assertIs(reduce_size, False)
        with patch("src.mcp_server.robot.os.link", side_effect=OSError(errno.EXDEV, "cross-device link")):
            await self.upload(intermediate)
        self.assertFalse(seen[0].exists())

    async def test_filename_only_signature(self):
        async def intermediate(filepath_local, collection_name, sub_collection_name, video_filename):
            self.assertEqual(video_filename, "ep_demo1.mp4")
            self.assertEqual(filepath_local, str(self.source))
        await self.upload(intermediate)

    async def test_variadic_signature_receives_both_keywords(self):
        async def wrapper(**kwargs):
            self.assertEqual(kwargs["video_filename"], "ep_demo1.mp4")
            self.assertIs(kwargs["reduce_size"], False)
        await self.upload(wrapper)

    async def test_public_sdk_signed_upload_uses_episode_filename(self):
        import httpx
        from unittest.mock import AsyncMock
        from vmodal.resources.collections import CollectionsResource
        from vmodal.routes import (
            _EXTERNAL_UPLOAD_GET_SIGNED_URL, _EXTERNAL_UPLOAD_DONE, full,
        )

        # Run the real SDK upload and completion code, replacing both HTTP
        # boundaries so this test cannot contact the API or object storage.
        request = AsyncMock(side_effect=[
            {"key": "fake-object-key", "url": "https://upload.invalid/clip", "method": "PUT"},
            {"dest_path": "demo/cam_scene/ep_demo1.mp4"},
        ])
        resource = CollectionsResource(SimpleNamespace(
            request=request, cfg=SimpleNamespace(timeout=5)))
        uploads = []

        async def object_store(incoming):
            uploads.append(incoming)
            self.assertEqual(incoming.method, "PUT")
            self.assertEqual(str(incoming.url), "https://upload.invalid/clip")
            self.assertEqual(await incoming.aread(), self.source.read_bytes())
            return httpx.Response(200)

        original_client = httpx.AsyncClient
        def offline_client(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(object_store)
            return original_client(*args, **kwargs)

        with patch("httpx.AsyncClient", side_effect=offline_client):
            result = await self.upload(resource.video_upload)

        self.assertTrue(result.uploaded)
        self.assertEqual(result.filename, "ep_demo1.mp4")
        self.assertEqual(len(uploads), 1)
        self.assertEqual(request.await_count, 2)
        for call, endpoint in zip(request.await_args_list, (
            _EXTERNAL_UPLOAD_GET_SIGNED_URL, _EXTERNAL_UPLOAD_DONE,
        )):
            self.assertEqual(call.args, ("POST", full(endpoint)))
            self.assertEqual(call.kwargs["params"]["filename"], "ep_demo1.mp4")
            self.assertEqual(call.kwargs["params"]["group_name"], "demo")
            self.assertEqual(call.kwargs["params"]["stream_name"], "cam_scene")
        self.assertEqual(request.await_args_list[1].kwargs["params"]["key"], "fake-object-key")

    async def test_errors_are_not_retried_and_alias_is_cleaned(self):
        seen = []
        async def legacy(filepath_local, collection_name, sub_collection_name):
            seen.append(Path(filepath_local))
            raise TypeError("internal upload error, not signature mismatch")
        with self.assertRaisesRegex(TypeError, "internal upload error"):
            await self.upload(legacy)
        self.assertEqual(len(seen), 1)
        self.assertFalse(seen[0].parent.exists())
        self.assertTrue(self.source.exists())

    async def test_cancellation_removes_alias(self):
        seen = []
        async def legacy(filepath_local, collection_name, sub_collection_name):
            seen.append(Path(filepath_local))
            raise asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.upload(legacy)
        self.assertFalse(seen[0].parent.exists())

    async def test_episode_upload_legacy_sdk_keeps_metadata_filename(self):
        from unittest.mock import AsyncMock
        from src.mcp_server.robot import robot_episode_upload, manifest_read
        from utils_datafake import robot_fake_case

        cfg, _, args, _ = robot_fake_case("legacy_sdk_upload")
        seen = []
        async def legacy(filepath_local, collection_name, sub_collection_name):
            path = Path(filepath_local)
            self.assertEqual(path.name, "ep_demo1.mp4")
            self.assertEqual(path.read_bytes(), Path(args[
                "video_scene" if sub_collection_name == "cam_scene" else "video_wrist"
            ]).read_bytes())
            seen.append(path)
        metadata = AsyncMock()
        client = SimpleNamespace(collections=SimpleNamespace(
            video_upload=legacy, upload_metadata_jsonl=metadata))
        result = await robot_episode_upload(cfg, client=client, **{**args, "dry_run": False})
        self.assertEqual(result["status"], "uploaded")
        self.assertEqual(result["episode"]["video"], "ep_demo1.mp4")
        self.assertEqual(manifest_read(cfg, "demo")[0]["status"], "uploaded")
        self.assertEqual(len(seen), 2)
        self.assertEqual(metadata.await_count, 2)
        self.assertTrue(all(not path.exists() for path in seen))

    async def test_concurrent_upload_aliases_are_isolated(self):
        seen = []
        async def legacy(filepath_local, collection_name, sub_collection_name):
            path = Path(filepath_local)
            seen.append(path)
            await asyncio.sleep(0)
            self.assertEqual(path.read_bytes(), self.source.read_bytes())
        await asyncio.gather(self.upload(legacy), self.upload(legacy))
        self.assertNotEqual(seen[0], seen[1])
        self.assertTrue(all(not path.parent.exists() for path in seen))


if __name__ == "__main__":
    unittest.main()
