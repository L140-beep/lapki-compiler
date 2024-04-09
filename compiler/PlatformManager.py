"""Module for managing platforms."""
import json
from typing import Dict, Set, List

from aiofile import async_open
from aiopath import AsyncPath
from compiler.config import PLATFORM_DIRECTORY
from compiler.types.inner_types import File

try:
    from .types.platform_types import Platform
except ImportError:
    from compiler.types.platform_types import Platform

PlatformId = str
PlatformVersion = str


async def __write_source(path: str, source_files: List[File]) -> None:
    for source in source_files:
        filename = f'{path}{source.filename}.{source.extension}'
        async with async_open(filename, 'w') as f:
            await f.write(source.fileContent)


class PlatformException(Exception):
    """Error during add platforms."""

    ...


class PlatformManager:
    """
    Класс-синглтон, отвечающий за загрузку платформ.

    TODO: А также их удаление из памяти, если их не используют
    какое-то время.
    """

    # Здесь будут храниться недавно использованные
    # платформы для быстрого доступа.
    platforms: dict[str, Platform] = {}
    # Здесь будет храниться список id платформ.
    platforms_versions_info: Dict[PlatformId, Set[PlatformVersion]] = {}

    @staticmethod
    async def save_platform(platform: Platform,
                            source_files: List[File]) -> None:
        """Save platform to folder."""
        platform_path = (PLATFORM_DIRECTORY + platform.id +
                         '/' + platform.version + '/')
        if await AsyncPath(platform_path).exists():
            raise PlatformException(
                f'Platform ({platform.id})'
                f'with version {platform.version} is already exists.')
        json_platform = platform.model_dump_json(indent=4)
        await AsyncPath(platform_path).mkdir(parents=True)
        await __write_source(platform_path, source_files)
        await __write_source(platform_path, [File(
            f'{platform.id}-{platform.version}', 'json', json_platform)])

    @staticmethod
    async def load_platform(path_to_platform: str | AsyncPath) -> None:
        """Load platform from file and add it to dict."""
        try:
            async with async_open(path_to_platform, 'r') as f:
                unprocessed_platform_data: str = await f.read()
                platform = Platform(
                    **json.loads(unprocessed_platform_data))
                if PlatformManager.platforms.get(platform.id, None) is None:
                    PlatformManager.platforms[platform.id] = platform
                else:
                    print(f'Platform with id {platform.id} is already exists.')
        except Exception as e:
            print(
                f'Во время обработки файла "{path_to_platform}"'
                f'произошла ошибка! {e}')

    @staticmethod
    async def init_platforms(path_to_schemas_dir: str) -> None:
        """Find platforms in path and add it to Dict."""
        print(f'Поиск схем в папке "{path_to_schemas_dir}"...')
        async for path in AsyncPath(path_to_schemas_dir).glob('*json'):
            await PlatformManager.load_platform(path)

        print(
            f'Были найдены платформы: {list(PlatformManager.platforms.keys())}'
        )

    @staticmethod
    def get_platform(platform_id: str, version: str) -> Platform:
        """Get platform by id."""
        platform: Platform | None = PlatformManager.platforms.get(platform_id)
        if platform is None:
            raise PlatformException(f'Unsupported platform {platform_id}')
        return platform
