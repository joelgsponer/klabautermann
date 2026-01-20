"""
Unit tests for ontology entity type models.

Tests the Pydantic models used by Graphiti for entity extraction.
"""

from __future__ import annotations

from klabautermann.core.ontology import (
    ENTITY_TYPES,
    CommunityType,
    HealthMetricType,
    HobbyType,
    LoreEpisodeType,
    MilestoneType,
    NodeLabel,
    OrganizationType,
    PersonType,
    PetType,
    PreferenceType,
    ProjectType,
    RelationType,
    RoutineType,
    TaskType,
)


# =============================================================================
# Test Core Entity Types
# =============================================================================


class TestPersonType:
    """Tests for PersonType model."""

    def test_default_values(self) -> None:
        """Test PersonType with default values."""
        person = PersonType()
        assert person.email is None
        assert person.title is None
        assert person.phone is None

    def test_with_all_fields(self) -> None:
        """Test PersonType with all fields populated."""
        person = PersonType(
            email="john@example.com",
            title="Software Engineer",
            phone="+1-555-0123",
        )
        assert person.email == "john@example.com"
        assert person.title == "Software Engineer"
        assert person.phone == "+1-555-0123"


class TestOrganizationType:
    """Tests for OrganizationType model."""

    def test_default_values(self) -> None:
        """Test OrganizationType with default values."""
        org = OrganizationType()
        assert org.industry is None
        assert org.domain is None

    def test_with_all_fields(self) -> None:
        """Test OrganizationType with all fields populated."""
        org = OrganizationType(
            industry="Technology",
            domain="acme.com",
        )
        assert org.industry == "Technology"
        assert org.domain == "acme.com"


class TestProjectType:
    """Tests for ProjectType model."""

    def test_default_values(self) -> None:
        """Test ProjectType with default values."""
        project = ProjectType()
        assert project.status is None
        assert project.deadline is None

    def test_with_all_fields(self) -> None:
        """Test ProjectType with all fields populated."""
        project = ProjectType(
            status="active",
            deadline="2024-12-31",
        )
        assert project.status == "active"
        assert project.deadline == "2024-12-31"


class TestTaskType:
    """Tests for TaskType model."""

    def test_default_values(self) -> None:
        """Test TaskType with default values."""
        task = TaskType()
        assert task.status is None
        assert task.priority is None
        assert task.due_date is None

    def test_with_all_fields(self) -> None:
        """Test TaskType with all fields populated."""
        task = TaskType(
            status="in_progress",
            priority="high",
            due_date="2024-03-15",
        )
        assert task.status == "in_progress"
        assert task.priority == "high"
        assert task.due_date == "2024-03-15"


# =============================================================================
# Test Personal Life Entity Types
# =============================================================================


class TestHobbyType:
    """Tests for HobbyType model."""

    def test_default_values(self) -> None:
        """Test HobbyType with default values."""
        hobby = HobbyType()
        assert hobby.category is None
        assert hobby.skill_level is None
        assert hobby.frequency is None

    def test_with_all_fields(self) -> None:
        """Test HobbyType with all fields populated."""
        hobby = HobbyType(
            category="sports",
            skill_level="intermediate",
            frequency="weekly",
        )
        assert hobby.category == "sports"
        assert hobby.skill_level == "intermediate"
        assert hobby.frequency == "weekly"

    def test_various_categories(self) -> None:
        """Test various hobby categories."""
        categories = ["sports", "arts", "music", "gaming", "outdoors", "crafts"]
        for cat in categories:
            hobby = HobbyType(category=cat)
            assert hobby.category == cat


class TestHealthMetricType:
    """Tests for HealthMetricType model."""

    def test_default_values(self) -> None:
        """Test HealthMetricType with default values."""
        metric = HealthMetricType()
        assert metric.metric_type is None
        assert metric.value is None
        assert metric.unit is None
        assert metric.recorded_at is None

    def test_with_all_fields(self) -> None:
        """Test HealthMetricType with all fields populated."""
        metric = HealthMetricType(
            metric_type="weight",
            value=75.5,
            unit="kg",
            recorded_at="2024-01-15T08:30:00",
        )
        assert metric.metric_type == "weight"
        assert metric.value == 75.5
        assert metric.unit == "kg"
        assert metric.recorded_at == "2024-01-15T08:30:00"

    def test_various_metric_types(self) -> None:
        """Test various health metric types."""
        metrics = [
            ("weight", 75.0, "kg"),
            ("blood_pressure", 120.0, "mmHg"),
            ("heart_rate", 72.0, "bpm"),
            ("steps", 10000.0, "steps"),
            ("sleep", 7.5, "hours"),
            ("glucose", 95.0, "mg/dL"),
        ]
        for metric_type, value, unit in metrics:
            metric = HealthMetricType(metric_type=metric_type, value=value, unit=unit)
            assert metric.metric_type == metric_type
            assert metric.value == value
            assert metric.unit == unit


class TestPetType:
    """Tests for PetType model."""

    def test_default_values(self) -> None:
        """Test PetType with default values."""
        pet = PetType()
        assert pet.species is None
        assert pet.breed is None
        assert pet.birth_date is None
        assert pet.adoption_date is None

    def test_with_all_fields(self) -> None:
        """Test PetType with all fields populated."""
        pet = PetType(
            species="dog",
            breed="Golden Retriever",
            birth_date="2020-05-15",
            adoption_date="2020-08-01",
        )
        assert pet.species == "dog"
        assert pet.breed == "Golden Retriever"
        assert pet.birth_date == "2020-05-15"
        assert pet.adoption_date == "2020-08-01"

    def test_various_species(self) -> None:
        """Test various pet species."""
        species_list = ["dog", "cat", "bird", "fish", "rabbit", "hamster"]
        for species in species_list:
            pet = PetType(species=species)
            assert pet.species == species


class TestMilestoneType:
    """Tests for MilestoneType model."""

    def test_default_values(self) -> None:
        """Test MilestoneType with default values."""
        milestone = MilestoneType()
        assert milestone.category is None
        assert milestone.significance is None
        assert milestone.achieved_at is None

    def test_with_all_fields(self) -> None:
        """Test MilestoneType with all fields populated."""
        milestone = MilestoneType(
            category="career",
            significance="major",
            achieved_at="2024-01-01",
        )
        assert milestone.category == "career"
        assert milestone.significance == "major"
        assert milestone.achieved_at == "2024-01-01"

    def test_various_categories(self) -> None:
        """Test various milestone categories."""
        categories = ["career", "education", "personal", "health", "relationship", "financial"]
        for cat in categories:
            milestone = MilestoneType(category=cat)
            assert milestone.category == cat

    def test_significance_levels(self) -> None:
        """Test various significance levels."""
        levels = ["minor", "moderate", "major", "life_changing"]
        for level in levels:
            milestone = MilestoneType(significance=level)
            assert milestone.significance == level


class TestRoutineType:
    """Tests for RoutineType model."""

    def test_default_values(self) -> None:
        """Test RoutineType with default values."""
        routine = RoutineType()
        assert routine.frequency is None
        assert routine.time_of_day is None
        assert routine.duration_minutes is None
        assert routine.is_active is True

    def test_with_all_fields(self) -> None:
        """Test RoutineType with all fields populated."""
        routine = RoutineType(
            frequency="daily",
            time_of_day="morning",
            duration_minutes=30,
            is_active=True,
        )
        assert routine.frequency == "daily"
        assert routine.time_of_day == "morning"
        assert routine.duration_minutes == 30
        assert routine.is_active is True

    def test_inactive_routine(self) -> None:
        """Test inactive routine."""
        routine = RoutineType(
            frequency="weekly",
            is_active=False,
        )
        assert routine.frequency == "weekly"
        assert routine.is_active is False

    def test_various_frequencies(self) -> None:
        """Test various routine frequencies."""
        frequencies = ["daily", "weekly", "monthly", "weekdays", "weekends"]
        for freq in frequencies:
            routine = RoutineType(frequency=freq)
            assert routine.frequency == freq


class TestPreferenceType:
    """Tests for PreferenceType model."""

    def test_default_values(self) -> None:
        """Test PreferenceType with default values."""
        pref = PreferenceType()
        assert pref.category is None
        assert pref.sentiment is None
        assert pref.strength is None
        assert pref.context is None

    def test_with_all_fields(self) -> None:
        """Test PreferenceType with all fields populated."""
        pref = PreferenceType(
            category="food",
            sentiment="love",
            strength=0.9,
            context="Grew up in Italy",
        )
        assert pref.category == "food"
        assert pref.sentiment == "love"
        assert pref.strength == 0.9
        assert pref.context == "Grew up in Italy"

    def test_various_sentiments(self) -> None:
        """Test various sentiment values."""
        sentiments = ["like", "dislike", "love", "hate", "neutral", "indifferent"]
        for sent in sentiments:
            pref = PreferenceType(sentiment=sent)
            assert pref.sentiment == sent

    def test_strength_bounds(self) -> None:
        """Test strength values at boundaries."""
        pref_weak = PreferenceType(strength=0.0)
        assert pref_weak.strength == 0.0

        pref_strong = PreferenceType(strength=1.0)
        assert pref_strong.strength == 1.0


class TestCommunityType:
    """Tests for CommunityType model."""

    def test_default_values(self) -> None:
        """Test CommunityType with default values."""
        community = CommunityType()
        assert community.theme is None
        assert community.summary is None
        assert community.node_count is None
        assert community.coherence_score is None

    def test_with_all_fields(self) -> None:
        """Test CommunityType with all fields populated."""
        community = CommunityType(
            theme="work_projects",
            summary="All nodes related to ongoing work projects",
            node_count=25,
            coherence_score=0.85,
        )
        assert community.theme == "work_projects"
        assert community.summary == "All nodes related to ongoing work projects"
        assert community.node_count == 25
        assert community.coherence_score == 0.85

    def test_various_themes(self) -> None:
        """Test various community themes."""
        themes = ["family", "work", "hobbies", "health", "finance", "travel"]
        for theme in themes:
            community = CommunityType(theme=theme)
            assert community.theme == theme


class TestLoreEpisodeType:
    """Tests for LoreEpisodeType model."""

    def test_default_values(self) -> None:
        """Test LoreEpisodeType with default values."""
        episode = LoreEpisodeType()
        assert episode.saga_id is None
        assert episode.chapter is None
        assert episode.told_at is None
        assert episode.topic is None
        assert episode.is_revealed is False

    def test_with_all_fields(self) -> None:
        """Test LoreEpisodeType with all fields populated."""
        episode = LoreEpisodeType(
            saga_id="career_journey",
            chapter=3,
            told_at="2024-01-15T10:00:00",
            topic="First promotion",
            is_revealed=True,
        )
        assert episode.saga_id == "career_journey"
        assert episode.chapter == 3
        assert episode.told_at == "2024-01-15T10:00:00"
        assert episode.topic == "First promotion"
        assert episode.is_revealed is True

    def test_unrevealed_episode(self) -> None:
        """Test unrevealed lore episode."""
        episode = LoreEpisodeType(
            saga_id="family_history",
            chapter=1,
            is_revealed=False,
        )
        assert episode.saga_id == "family_history"
        assert episode.is_revealed is False

    def test_chapter_sequence(self) -> None:
        """Test various chapter numbers."""
        for chapter in [1, 5, 10, 50, 100]:
            episode = LoreEpisodeType(chapter=chapter)
            assert episode.chapter == chapter


# =============================================================================
# Test ENTITY_TYPES Dict
# =============================================================================


class TestEntityTypes:
    """Tests for ENTITY_TYPES dictionary."""

    def test_contains_core_types(self) -> None:
        """Test that ENTITY_TYPES contains core entity types."""
        assert "Person" in ENTITY_TYPES
        assert "Organization" in ENTITY_TYPES
        assert "Project" in ENTITY_TYPES
        assert "Location" in ENTITY_TYPES
        assert "Event" in ENTITY_TYPES
        assert "Task" in ENTITY_TYPES
        assert "Email" in ENTITY_TYPES

    def test_contains_personal_life_types(self) -> None:
        """Test that ENTITY_TYPES contains personal life entity types."""
        assert "Hobby" in ENTITY_TYPES
        assert "HealthMetric" in ENTITY_TYPES
        assert "Pet" in ENTITY_TYPES
        assert "Milestone" in ENTITY_TYPES
        assert "Routine" in ENTITY_TYPES
        assert "Preference" in ENTITY_TYPES
        assert "Community" in ENTITY_TYPES
        assert "LoreEpisode" in ENTITY_TYPES

    def test_types_are_pydantic_models(self) -> None:
        """Test that all entity types are Pydantic BaseModel subclasses."""
        from pydantic import BaseModel

        for name, model in ENTITY_TYPES.items():
            assert issubclass(model, BaseModel), f"{name} is not a BaseModel subclass"

    def test_total_entity_count(self) -> None:
        """Test total number of entity types."""
        # 7 core + 8 personal life = 15
        assert len(ENTITY_TYPES) == 15


# =============================================================================
# Test NodeLabel Enum
# =============================================================================


class TestNodeLabel:
    """Tests for NodeLabel enum."""

    def test_core_labels_exist(self) -> None:
        """Test that core labels exist."""
        assert NodeLabel.PERSON.value == "Person"
        assert NodeLabel.ORGANIZATION.value == "Organization"
        assert NodeLabel.PROJECT.value == "Project"
        assert NodeLabel.TASK.value == "Task"

    def test_personal_life_labels_exist(self) -> None:
        """Test that personal life labels exist."""
        assert NodeLabel.HOBBY.value == "Hobby"
        assert NodeLabel.HEALTH_METRIC.value == "HealthMetric"
        assert NodeLabel.PET.value == "Pet"
        assert NodeLabel.MILESTONE.value == "Milestone"
        assert NodeLabel.ROUTINE.value == "Routine"

    def test_system_labels_exist(self) -> None:
        """Test that system labels exist."""
        assert NodeLabel.THREAD.value == "Thread"
        assert NodeLabel.MESSAGE.value == "Message"
        assert NodeLabel.DAY.value == "Day"


# =============================================================================
# Test RelationType Enum
# =============================================================================


class TestRelationType:
    """Tests for RelationType enum."""

    def test_professional_relations_exist(self) -> None:
        """Test that professional relationship types exist."""
        assert RelationType.WORKS_AT.value == "WORKS_AT"
        assert RelationType.REPORTS_TO.value == "REPORTS_TO"
        assert RelationType.ASSIGNED_TO.value == "ASSIGNED_TO"

    def test_personal_life_relations_exist(self) -> None:
        """Test that personal life relationship types exist."""
        assert RelationType.PRACTICES.value == "PRACTICES"
        assert RelationType.OWNS.value == "OWNS"
        assert RelationType.CARES_FOR.value == "CARES_FOR"
        assert RelationType.FOLLOWS_ROUTINE.value == "FOLLOWS_ROUTINE"
        assert RelationType.ACHIEVES.value == "ACHIEVES"

    def test_family_relations_exist(self) -> None:
        """Test that family relationship types exist."""
        assert RelationType.FAMILY_OF.value == "FAMILY_OF"
        assert RelationType.SPOUSE_OF.value == "SPOUSE_OF"
        assert RelationType.PARENT_OF.value == "PARENT_OF"
        assert RelationType.CHILD_OF.value == "CHILD_OF"
