import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django_celery_beat.models import CrontabSchedule, PeriodicTask

from app.models import (
    TV,
    Anime,
    Book,
    Episode,
    Game,
    Item,
    Manga,
    MediaTypes,
    Movie,
    Season,
    Sources,
    Status,
)
from integrations.imports import anilist, goodreads, helpers, hltb, kitsu, mal, simkl, yamtrack
from integrations.imports.trakt import TraktImporter, importer

mock_path = Path(__file__).resolve().parent / "mock_data"
app_mock_path = (
    Path(__file__).resolve().parent.parent.parent / "app" / "tests" / "mock_data"
)


class ImportMAL(TestCase):
    """Test importing media from MyAnimeList."""

    def setUp(self):
        """Create user for the tests."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

    @patch("requests.Session.get")
    def test_import_animelist(self, mock_request):
        """Basic test importing anime and manga from MyAnimeList."""
        with Path(mock_path / "import_mal_anime.json").open() as file:
            anime_response = json.load(file)
        with Path(mock_path / "import_mal_manga.json").open() as file:
            manga_response = json.load(file)

        anime_mock = MagicMock()
        anime_mock.json.return_value = anime_response
        manga_mock = MagicMock()
        manga_mock.json.return_value = manga_response
        mock_request.side_effect = [anime_mock, manga_mock]

        mal.importer("bloodthirstiness", self.user, "new")
        self.assertEqual(Anime.objects.filter(user=self.user).count(), 5)
        self.assertEqual(Manga.objects.filter(user=self.user).count(), 3)

        self.assertEqual(
            Anime.objects.filter(
                user=self.user,
                item__title="Ama Gli Animali",
            )
            .first()
            .item.image,
            settings.IMG_NONE,
        )
        self.assertEqual(
            Anime.objects.get(user=self.user, item__title="FLCL").status,
            Status.PAUSED.value,
        )
        self.assertEqual(
            Manga.objects.get(user=self.user, item__title="Fire Punch").score,
            7,
        )

        self.assertEqual(
            Anime.objects.filter(
                user=self.user,
                item__title="Chainsaw Man",
            )
            .first()
            .history.first()
            .history_date,
            datetime(2022, 12, 28, 19, 20, 54, tzinfo=UTC),
        )

    def test_user_not_found(self):
        """Test that an error is raised if the user is not found."""
        self.assertRaises(
            helpers.MediaImportError,
            mal.importer,
            "fhdsufdsu",
            self.user,
            "new",
        )


class ImportAniList(TestCase):
    """Test importing media from AniList."""

    def setUp(self):
        """Create user for the tests."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

    @patch("requests.Session.post")
    def test_import_anilist(self, mock_request):
        """Basic test importing anime and manga from AniList."""
        with Path(mock_path / "import_anilist.json").open() as file:
            anilist_response = json.load(file)
        mock_request.return_value.json.return_value = anilist_response

        anilist.importer("bloodthirstiness", self.user, "new")
        self.assertEqual(Anime.objects.filter(user=self.user).count(), 4)
        self.assertEqual(Manga.objects.filter(user=self.user).count(), 3)
        self.assertEqual(
            Anime.objects.get(user=self.user, item__title="FLCL").status,
            Status.PAUSED.value,
        )
        self.assertEqual(
            Manga.objects.filter(user=self.user, item__title="One Punch-Man")
            .first()
            .score,
            9,
        )
        self.assertEqual(
            Anime.objects.get(user=self.user, item__title="FLCL")
            .history.first()
            .history_date,
            datetime(2025, 6, 4, 10, 11, 17, tzinfo=UTC),
        )

    def test_user_not_found(self):
        """Test that an error is raised if the user is not found."""
        self.assertRaises(
            helpers.MediaImportError,
            anilist.importer,
            "fhdsufdsu",
            self.user,
            "new",
        )


class ImportYamtrack(TestCase):
    """Test importing media from Yamtrack CSV."""

    def setUp(self):
        """Create user for the tests."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        with Path(mock_path / "import_yamtrack.csv").open("rb") as file:
            self.import_results = yamtrack.importer(file, self.user, "new")

    def test_import_counts(self):
        """Test basic counts of imported media."""
        self.assertEqual(Anime.objects.filter(user=self.user).count(), 1)
        self.assertEqual(Manga.objects.filter(user=self.user).count(), 1)
        self.assertEqual(TV.objects.filter(user=self.user).count(), 1)
        self.assertEqual(Movie.objects.filter(user=self.user).count(), 1)
        self.assertEqual(Season.objects.filter(user=self.user).count(), 1)
        self.assertEqual(
            Episode.objects.filter(related_season__user=self.user).count(),
            24,
        )

    def test_historical_records(self):
        """Test historical records creation during import."""
        anime = Anime.objects.filter(user=self.user).first()
        self.assertEqual(anime.history.count(), 1)
        self.assertEqual(
            anime.history.first().history_date,
            datetime(2024, 2, 9, 10, 0, 0, tzinfo=UTC),
        )

        movie = Movie.objects.filter(user=self.user).first()
        self.assertEqual(movie.history.count(), 1)
        self.assertEqual(
            movie.history.first().history_date,
            datetime(2024, 2, 9, 15, 30, 0, tzinfo=UTC),
        )

        tv = TV.objects.filter(user=self.user).first()
        self.assertEqual(tv.history.count(), 1)
        self.assertEqual(
            tv.history.first().history_date,
            datetime(2024, 2, 9, 12, 0, 0, tzinfo=UTC),
        )

    def test_missing_metadata_handling(self):
        """Test _handle_missing_metadata method directly."""
        # Create test rows for different media types
        test_rows = [
            # TV Show
            {
                "media_id": "1668",
                "source": "tmdb",
                "media_type": "tv",
                "title": "",
                "image": "",
                "season_number": "",
                "episode_number": "",
            },
            # Season
            {
                "media_id": "1668",
                "source": "tmdb",
                "media_type": "season",
                "title": "",
                "image": "",
                "season_number": "2",
                "episode_number": "",
            },
            # Episode
            {
                "media_id": "1668",
                "source": "tmdb",
                "media_type": "episode",
                "title": "",
                "image": "",
                "season_number": "2",
                "episode_number": "5",
            },
        ]

        importer = yamtrack.YamtrackImporter(None, self.user, "new")

        for row in test_rows:
            # Make copies of original rows to verify they're modified
            original_row = row.copy()

            # Call the method directly
            importer._handle_missing_metadata(
                row,
                row["media_type"],
                row["season_number"],
                row["episode_number"],
            )

            # Verify the row was modified as expected
            self.assertNotEqual(row["title"], original_row["title"])
            self.assertNotEqual(row["image"], original_row["image"])


class ImportYamtrackPartials(TestCase):
    """Test importing yamtrack media with no ID."""

    def setUp(self):
        """Create user for the tests."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        with Path(mock_path / "import_yamtrack_partials.csv").open("rb") as file:
            self.import_results = yamtrack.importer(file, self.user, "new")

    def test_import_counts(self):
        """Test basic counts of imported media."""
        self.assertEqual(Book.objects.filter(user=self.user).count(), 3)
        self.assertEqual(Movie.objects.filter(user=self.user).count(), 1)

    def test_end_dates(self):
        """Test end dates during import."""
        book = Book.objects.filter(user=self.user).first()
        self.assertEqual(book.history.count(), 1)
        bookqs = Book.objects.filter(
            user=self.user,
            item__title="Warlock",
        ).order_by("-end_date")
        books = list(bookqs)

        self.assertEqual(len(books), 3)
        self.assertEqual(
            books[0].end_date,
            datetime(2024, 5, 9, 0, 0, 0, tzinfo=UTC),
        )
        self.assertEqual(
            books[1].end_date,
            datetime(2024, 4, 9, 0, 0, 0, tzinfo=UTC),
        )
        self.assertEqual(
            books[2].end_date,
            datetime(2024, 3, 9, 0, 0, 0, tzinfo=UTC),
        )


class ImportHowLongToBeat(TestCase):
    """Test importing media from HowLongToBeat CSV."""

    def setUp(self):
        """Create user for the tests."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        with Path(mock_path / "import_hltb_game.csv").open("rb") as file:
            self.import_results = hltb.importer(file, self.user, "new")

    def test_import_counts(self):
        """Test basic counts of imported games."""
        self.assertEqual(Game.objects.filter(user=self.user).count(), 1)

    def test_historical_records(self):
        """Test historical records creation during import."""
        game = Game.objects.filter(user=self.user).first()
        self.assertEqual(game.history.count(), 1)
        self.assertEqual(
            game.history.first().history_date,
            datetime(2024, 2, 9, 15, 54, 48, tzinfo=UTC),
        )


class ImportKitsu(TestCase):
    """Test importing media from Kitsu."""

    def setUp(self):
        """Create user for the tests."""
        credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**credentials)

        with Path(mock_path / "import_kitsu_anime.json").open() as file:
            self.sample_anime_response = json.load(file)

        with Path(mock_path / "import_kitsu_manga.json").open() as file:
            self.sample_manga_response = json.load(file)

        self.importer = kitsu.KitsuImporter("testuser", self.user, "new")

    @patch("app.providers.services.api_request")
    def test_get_kitsu_id(self, mock_api_request):
        """Test getting Kitsu ID from username."""
        mock_api_request.return_value = {
            "data": [{"id": "12345"}],
        }
        kitsu_id = self.importer._get_kitsu_id("testuser")
        self.assertEqual(kitsu_id, "12345")

    @patch("app.providers.services.api_request")
    def test_get_media_response(self, mock_api_request):
        """Test getting media response from Kitsu."""
        mock_api_request.side_effect = [
            self.sample_anime_response,
            self.sample_manga_response,
        ]

        imported_counts, warning_message = kitsu.importer(
            "123",
            self.user,
            "new",
        )
        self.assertEqual(imported_counts[MediaTypes.ANIME.value], 6)
        self.assertEqual(imported_counts[MediaTypes.MANGA.value], 6)
        self.assertEqual(warning_message, "")

        # Check if the media was imported
        self.assertEqual(Anime.objects.count(), 6)
        self.assertEqual(Manga.objects.count(), 6)
        self.assertEqual(
            Anime.objects.get(item__title="Test Anime 2").history.first().history_date,
            datetime(2024, 4, 8, 16, 16, 59, 18000, tzinfo=UTC),
        )

    def test_get_rating(self):
        """Test getting rating from Kitsu."""
        self.assertEqual(self.importer._get_rating(20), 10)
        self.assertEqual(self.importer._get_rating(10), 5)
        self.assertEqual(self.importer._get_rating(1), 0.5)
        self.assertIsNone(self.importer._get_rating(None))

    def test_get_status(self):
        """Test getting status from Kitsu."""
        self.assertEqual(self.importer._get_status("completed"), Status.COMPLETED.value)
        self.assertEqual(self.importer._get_status("current"), Status.IN_PROGRESS.value)
        self.assertEqual(self.importer._get_status("planned"), Status.PLANNING.value)
        self.assertEqual(self.importer._get_status("on_hold"), Status.PAUSED.value)

    def test_process_entry(self):
        """Test processing an entry from Kitsu."""
        entry = self.sample_anime_response["data"][0]
        media_lookup = {
            item["id"]: item
            for item in self.sample_anime_response["included"]
            if item["type"] == "anime"
        }
        mapping_lookup = {
            item["id"]: item
            for item in self.sample_anime_response["included"]
            if item["type"] == "mappings"
        }

        self.importer._process_entry(
            entry,
            MediaTypes.ANIME.value,
            media_lookup,
            mapping_lookup,
        )

        instance = self.importer.bulk_media[MediaTypes.ANIME.value][0]

        self.assertEqual(instance.item.media_id, "1")
        self.assertIsInstance(instance, Anime)
        self.assertEqual(instance.score, 9)
        self.assertEqual(instance.progress, 26)
        self.assertEqual(instance.status, Status.COMPLETED.value)
        self.assertEqual(instance.notes, "Great series!")


class ImportTrakt(TestCase):
    """Test importing media from Trakt."""

    def setUp(self):
        """Create user for the tests."""
        credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**credentials)

    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_process_watched_movie(self, mock_get_metadata):
        """Test processing a movie entry."""
        movie_entry = {
            "type": "movie",
            "movie": {"title": "Test Movie", "ids": {"tmdb": 67890}},
            "watched_at": "2023-01-02T00:00:00.000Z",
        }

        mock_get_metadata.return_value = {
            "title": "Test Movie",
            "image": "movie_image.jpg",
        }

        trakt_importer = TraktImporter("test", self.user, "new")
        trakt_importer.process_watched_movie(movie_entry)

        # Check that the movie was added to bulk media
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.MOVIE.value]), 1)
        self.assertEqual(len(trakt_importer.media_instances[MediaTypes.MOVIE.value]), 1)

        # Process the same movie again to test repeat handling
        trakt_importer.process_watched_movie(movie_entry)
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.MOVIE.value]), 2)

    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_process_watched_episode(self, mock_get_metadata):
        """Test processing an episode entry."""
        episode_entry = {
            "type": "episode",
            "episode": {"season": 1, "number": 1, "title": "Pilot"},
            "show": {"title": "Test Show", "ids": {"tmdb": 12345}},
            "watched_at": "2023-01-01T00:00:00.000Z",
        }

        # Mock metadata for TV, Season, and Episode
        def mock_metadata_side_effect(media_type, _, __, ___=None):
            if media_type == MediaTypes.TV.value:
                return {
                    "title": "Test Show",
                    "image": "tv_image.jpg",
                    "last_episode_season": 1,
                    "max_progress": 1,
                }
            if media_type == MediaTypes.SEASON.value:
                return {
                    "title": "Season 1",
                    "image": "season_image.jpg",
                    "episodes": [{"episode_number": 1, "still_path": "/still.jpg"}],
                    "max_progress": 1,
                }
            return None

        mock_get_metadata.side_effect = mock_metadata_side_effect

        trakt_importer = TraktImporter("testuser", self.user, "new")
        trakt_importer.process_watched_episode(episode_entry)

        # Check that all objects were added to bulk media
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.TV.value]), 1)
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.SEASON.value]), 1)
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.EPISODE.value]), 1)

        # Process the same episode again to test repeat handling
        trakt_importer.process_watched_episode(episode_entry)
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.EPISODE.value]), 2)

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_process_watchlist(self, mock_get_metadata, mock_make_request):
        """Test processing a watchlist entry."""
        watchlist_entry = {
            "listed_at": "2023-01-01T00:00:00.000Z",
            "type": "show",
            "show": {"title": "Watchlist Show", "ids": {"tmdb": 54321}},
        }

        mock_make_request.return_value = [watchlist_entry]
        mock_get_metadata.return_value = {
            "title": "Watchlist Show",
            "image": "show_image.jpg",
        }

        trakt_importer = TraktImporter("testuser", self.user, "new")
        trakt_importer.process_watchlist()

        # Check that TV was added to bulk media with planning status
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.TV.value]), 1)
        tv_obj = trakt_importer.bulk_media[MediaTypes.TV.value][0]
        self.assertEqual(tv_obj.status, Status.PLANNING.value)

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_process_ratings(self, mock_get_metadata, mock_make_request):
        """Test processing a rating entry."""
        rating_entry = {
            "rated_at": "2023-01-01T00:00:00.000Z",
            "type": "movie",
            "movie": {"title": "Rated Movie", "ids": {"tmdb": 238}},
            "rating": 8,
        }

        mock_make_request.return_value = [rating_entry]
        mock_get_metadata.return_value = {
            "title": "Rated Movie",
            "image": "movie_image.jpg",
        }

        trakt_importer = TraktImporter("testuser", self.user, "new")
        trakt_importer.process_ratings()

        # Check that movie was added to bulk media with score
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.MOVIE.value]), 1)
        movie_obj = trakt_importer.bulk_media[MediaTypes.MOVIE.value][0]
        self.assertEqual(movie_obj.score, 8)

    @patch("integrations.imports.trakt.TraktImporter._make_api_request")
    @patch("integrations.imports.trakt.TraktImporter._get_metadata")
    def test_process_comments(self, mock_get_metadata, mock_make_request):
        """Test processing paginated comments from Trakt."""
        # First page with one comment
        first_page = [
            {
                "type": "movie",
                "movie": {"title": "Commented Movie", "ids": {"tmdb": 123}},
                "comment": {
                    "comment": "Great movie!",
                    "updated_at": "2023-01-01T00:00:00.000Z",
                },
            },
        ]

        # Second empty page to stop pagination
        second_page = []

        mock_make_request.side_effect = [first_page, second_page]
        mock_get_metadata.return_value = {
            "title": "Commented Movie",
            "image": "movie_image.jpg",
        }

        trakt_importer = TraktImporter("testuser", self.user, "new")
        trakt_importer.process_comments()

        # Verify API was called with pagination parameters
        calls = mock_make_request.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertIn("?page=1&limit=1000", calls[0].args[0])  # First page
        self.assertIn("?page=2&limit=1000", calls[1].args[0])  # Second page

        # Check that movie was added to bulk media with comment
        self.assertEqual(len(trakt_importer.bulk_media[MediaTypes.MOVIE.value]), 1)
        movie_obj = trakt_importer.bulk_media[MediaTypes.MOVIE.value][0]
        self.assertEqual(movie_obj.notes, "Great movie!")

    @patch("integrations.imports.trakt.TraktImporter.import_data")
    def test_importer_function(self, mock_import_data):
        """Test the main importer function."""
        mock_import_data.return_value = (1, 2, 3, 4, "No warnings")

        result = importer("testuser", self.user, "new")

        # Check that the result is passed through correctly
        self.assertEqual(result, (1, 2, 3, 4, "No warnings"))


class ImportSimkl(TestCase):
    """Test importing media from SIMKL."""

    def setUp(self):
        """Create user for the tests."""
        credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**credentials)
        self.importer = simkl.SimklImporter("testuser", self.user, "new")

    @patch("integrations.imports.simkl.SimklImporter._get_user_list")
    def test_importer(
        self,
        user_list,
    ):
        """Test importing media from SIMKL."""
        # Mock API response
        user_list.return_value = {
            "shows": [
                {
                    "last_watched_at": "2023-01-02T00:00:00Z",
                    "show": {"title": "Breaking Bad", "ids": {"tmdb": 1396}},
                    "status": "watching",
                    "user_rating": 8,
                    "seasons": [
                        {
                            "number": 1,
                            "episodes": [
                                {"number": 1},
                                {"number": 2, "watched_at": "2023-01-02T00:00:00Z"},
                            ],
                        },
                    ],
                    "memo": {},
                },
            ],
            "movies": [
                {
                    "added_to_watchlist_at": "2023-01-01T00:00:00Z",
                    "movie": {"title": "Perfect Blue", "ids": {"tmdb": 10494}},
                    "status": "completed",
                    "user_rating": 9,
                    "last_watched_at": "2023-02-01T00:00:00Z",
                    "memo": {},
                },
            ],
            "anime": [
                {
                    "added_to_watchlist_at": "2023-01-01T00:00:00Z",
                    "show": {"title": "Example Anime", "ids": {"mal": 1}},
                    "status": "plantowatch",
                    "user_rating": 7,
                    "watched_episodes_count": 0,
                    "last_watched_at": None,
                    "memo": {"text": "Great series!"},
                },
            ],
        }

        imported_counts, warnings = simkl.importer(
            "token",
            self.user,
            "new",
        )

        # Check the results
        self.assertEqual(imported_counts[MediaTypes.TV.value], 1)
        self.assertEqual(imported_counts[MediaTypes.MOVIE.value], 1)
        self.assertEqual(imported_counts[MediaTypes.ANIME.value], 1)
        self.assertEqual(warnings, "")

        # Check TV show
        tv_item = Item.objects.get(media_type=MediaTypes.TV.value)
        self.assertEqual(tv_item.title, "Breaking Bad")
        tv_obj = TV.objects.get(item=tv_item)
        self.assertEqual(tv_obj.status, Status.IN_PROGRESS.value)
        self.assertEqual(tv_obj.score, 8)

        # Check Movie
        movie_item = Item.objects.get(media_type=MediaTypes.MOVIE.value)
        self.assertEqual(movie_item.title, "Perfect Blue")
        movie_obj = Movie.objects.get(item=movie_item)
        self.assertEqual(movie_obj.status, Status.COMPLETED.value)
        self.assertEqual(movie_obj.score, 9)

        # Check Anime
        anime_item = Item.objects.get(media_type=MediaTypes.ANIME.value)
        self.assertEqual(anime_item.title, "Cowboy Bebop")
        anime_obj = Anime.objects.get(item=anime_item)
        self.assertEqual(anime_obj.status, Status.PLANNING.value)
        self.assertEqual(anime_obj.score, 7)
        self.assertEqual(anime_obj.notes, "Great series!")

    def test_get_status(self):
        """Test mapping SIMKL status to internal status."""
        self.assertEqual(self.importer._get_status("completed"), Status.COMPLETED.value)
        self.assertEqual(
            self.importer._get_status("watching"),
            Status.IN_PROGRESS.value,
        )
        self.assertEqual(
            self.importer._get_status("plantowatch"),
            Status.PLANNING.value,
        )
        self.assertEqual(self.importer._get_status("hold"), Status.PAUSED.value)
        self.assertEqual(self.importer._get_status("dropped"), Status.DROPPED.value)
        self.assertEqual(
            self.importer._get_status("unknown"),
            Status.IN_PROGRESS.value,
        )  # Default case

    def test_get_date(self):
        """Test getting date from SIMKL."""
        self.assertEqual(
            self.importer._get_date("2023-01-01T00:00:00Z"),
            datetime(2023, 1, 1, 0, 0, 0, tzinfo=UTC),
        )
        self.assertIsNone(self.importer._get_date(None))

    @patch("integrations.imports.simkl.SimklImporter._get_user_list")
    @patch("app.providers.tmdb.tv_with_seasons")
    def test_season_status_logic_with_completed_seasons(
        self,
        mock_tv_with_seasons,
        mock_user_list,
    ):
        """Test that seasons are marked as completed when all episodes are watched."""
        # Mock TMDB metadata response
        mock_tv_with_seasons.return_value = {
            "title": "Breaking Bad",
            "image": "https://image.tmdb.org/t/p/w500/test.jpg",
            "season/1": {
                "image": "https://image.tmdb.org/t/p/w500/season1.jpg",
                "max_progress": 7,
                "episodes": [
                    {"episode_number": 1, "still_path": "/ep1.jpg"},
                    {"episode_number": 2, "still_path": "/ep2.jpg"},
                    {"episode_number": 3, "still_path": "/ep3.jpg"},
                    {"episode_number": 4, "still_path": "/ep4.jpg"},
                    {"episode_number": 5, "still_path": "/ep5.jpg"},
                    {"episode_number": 6, "still_path": "/ep6.jpg"},
                    {"episode_number": 7, "still_path": "/ep7.jpg"},
                ],
            },
            "season/2": {
                "image": "https://image.tmdb.org/t/p/w500/season2.jpg",
                "max_progress": 13,
            },
        }

        mock_user_list.return_value = {
            "shows": [
                {
                    "last_watched_at": "2023-01-15T00:00:00Z",
                    "show": {"title": "Breaking Bad", "ids": {"tmdb": 1396}},
                    "status": "watching",  # TV show is still in progress
                    "user_rating": 9,
                    "seasons": [
                        {
                            "number": 1,
                            "episodes": [
                                {"number": 1, "watched_at": "2023-01-01T00:00:00Z"},
                                {"number": 2, "watched_at": "2023-01-02T00:00:00Z"},
                                {"number": 3, "watched_at": "2023-01-03T00:00:00Z"},
                                {"number": 4, "watched_at": "2023-01-04T00:00:00Z"},
                                {"number": 5, "watched_at": "2023-01-05T00:00:00Z"},
                                {"number": 6, "watched_at": "2023-01-06T00:00:00Z"},
                                {"number": 7, "watched_at": "2023-01-07T00:00:00Z"},
                            ],
                        },
                    ],
                    "memo": {},
                },
            ],
            "movies": [],
            "anime": [],
        }

        imported_counts, warnings = simkl.importer("token", self.user, "new")

        # Verify import counts
        self.assertEqual(imported_counts[MediaTypes.TV.value], 1)
        self.assertEqual(imported_counts[MediaTypes.SEASON.value], 1)
        self.assertEqual(
            imported_counts[MediaTypes.EPISODE.value],
            7,
        )

        # Check TV show status
        tv_item = Item.objects.get(media_type=MediaTypes.TV.value)
        tv_obj = TV.objects.get(item=tv_item)
        self.assertEqual(tv_obj.status, Status.IN_PROGRESS.value)

        # Check Season 1 - should be COMPLETED because all 7 episodes are watched
        season1_item = Item.objects.get(
            media_type=MediaTypes.SEASON.value,
            season_number=1,
        )
        season1_obj = Season.objects.get(item=season1_item)
        self.assertEqual(
            season1_obj.status,
            Status.COMPLETED.value,
            "Season 1 should be completed when all episodes are watched",
        )

        # Verify all episodes were created correctly
        season1_episodes = Episode.objects.filter(
            item__season_number=1,
            item__media_type=MediaTypes.EPISODE.value,
        )
        self.assertEqual(season1_episodes.count(), 7)

        # Verify episode dates are set correctly
        for episode in season1_episodes:
            self.assertIsNotNone(episode.end_date)


class ImportGoodreads(TestCase):
    """Test importing media from GoodReads CSV."""

    def setUp(self):
        """Create user for the tests."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        with Path(mock_path / "import_goodreads.csv").open("rb") as file:
            self.import_results = goodreads.importer(file, self.user, "new")

    def test_import_counts(self):
        """Test basic counts of imported books."""
        self.assertEqual(Book.objects.filter(user=self.user).count(), 3)

    def test_historical_records(self):
        """Test historical records creation during import."""
        book = Book.objects.filter(user=self.user).first()
        self.assertEqual(book.history.count(), 1)


class HelpersTest(TestCase):
    """Test helper functions for imports."""

    def setUp(self):
        """Set up test data."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

    def test_update_season_references(self):
        """Test updating season references with actual TV instances."""
        # Create test data
        item = Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Test Show",
        )
        tv = TV.objects.create(
            item=item,
            user=self.user,
            status=Status.PLANNING.value,
        )

        # Create season with unsaved TV reference
        new_season = Season(
            item=item,
            user=self.user,
            related_tv=TV(item=item, user=self.user),
        )

        # Update references
        helpers.update_season_references([new_season], self.user)

        # Check if reference was updated
        self.assertEqual(new_season.related_tv.id, tv.id)

    def test_update_episode_references(self):
        """Test updating episode references with actual Season instances."""
        tv_item = Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Test Show",
        )
        tv = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.PLANNING.value,
        )

        season_item = Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Test Show",
            season_number=1,
        )
        season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=tv,
            status=Status.PLANNING.value,
        )

        episode_item = Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Test Show",
            season_number=1,
            episode_number=1,
        )

        # Create episode with unsaved Season reference
        new_episode = Episode(
            item=episode_item,
            related_season=Season(item=season_item, related_tv=tv, user=self.user),
        )

        # Update references
        helpers.update_episode_references([new_episode], self.user)

        # Check if reference was updated
        self.assertEqual(new_episode.related_season.id, season.id)

    @patch("django.contrib.messages.error")
    def test_create_import_schedule(self, mock_messages):
        """Test creating import schedule."""
        request = Mock()
        request.user = self.user

        # Test valid schedule creation
        helpers.create_import_schedule(
            "testuser",
            request,
            "new",
            "daily",
            "14:30",
            "TestSource",
        )

        # Check if schedule was created
        schedule = PeriodicTask.objects.first()
        self.assertIsNotNone(schedule)
        self.assertEqual(
            schedule.name,
            "Import from TestSource for testuser at 14:30:00 daily",
        )

        # Test duplicate schedule
        helpers.create_import_schedule(
            "testuser",
            request,
            "new",
            "daily",
            "14:30",
            "TestSource",
        )
        mock_messages.assert_called_with(
            request,
            "The same import task is already scheduled.",
        )

    @patch("django.contrib.messages.error")
    def test_create_import_schedule_invalid_time(self, mock_messages):
        """Test creating import schedule with invalid time."""
        request = Mock()
        request.user = self.user

        helpers.create_import_schedule(
            "testuser",
            request,
            "new",
            "daily",
            "25:00",  # Invalid time
            "TestSource",
        )

        mock_messages.assert_called_with(request, "Invalid import time.")
        self.assertEqual(PeriodicTask.objects.count(), 0)

    def test_create_import_schedule_every_2_days(self):
        """Test creating import schedule for every 2 days."""
        request = Mock()
        request.user = self.user

        helpers.create_import_schedule(
            "testuser",
            request,
            "new",
            "every_2_days",
            "14:30",
            "TestSource",
        )

        schedule = CrontabSchedule.objects.first()
        self.assertEqual(schedule.day_of_week, "*/2")
