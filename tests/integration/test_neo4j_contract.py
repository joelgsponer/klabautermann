"""
Contract tests for Neo4jClient.

Verifies that Neo4j query results have expected structure.
Tests run against real Neo4j instance on test port (7688).

IMPORTANT: Tests define what code SHOULD do according to specs.
If tests fail, fix the CODE, not the tests.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from tests.conftest import requires_neo4j


if TYPE_CHECKING:
    from klabautermann.memory.neo4j_client import Neo4jClient


@pytest.mark.integration
@requires_neo4j
class TestNeo4jClientContract:
    """Contract tests for Neo4jClient basic operations."""

    @pytest.mark.asyncio
    async def test_execute_query_returns_list_of_dicts(
        self,
        neo4j_client: Neo4jClient,
    ) -> None:
        """execute_query should return list of dicts."""
        result = await neo4j_client.execute_query(
            "RETURN 1 as value, 'test' as name",
            {},
        )

        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], dict)
        assert result[0]["value"] == 1
        assert result[0]["name"] == "test"

    @pytest.mark.asyncio
    async def test_execute_query_empty_result(
        self,
        neo4j_client: Neo4jClient,
    ) -> None:
        """execute_query returns empty list when no matches."""
        result = await neo4j_client.execute_query(
            "MATCH (n:NonExistentLabel12345) RETURN n",
            {},
        )

        assert isinstance(result, list)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_execute_query_with_parameters(
        self,
        neo4j_client: Neo4jClient,
    ) -> None:
        """execute_query correctly uses parameters."""
        result = await neo4j_client.execute_query(
            "RETURN $value as value, $name as name",
            {"value": 42, "name": "test_param"},
        )

        assert result[0]["value"] == 42
        assert result[0]["name"] == "test_param"


@pytest.mark.integration
@requires_neo4j
class TestNeo4jNodeOperations:
    """Contract tests for Neo4j node CRUD operations."""

    @pytest.mark.asyncio
    async def test_create_node_returns_node_dict(
        self,
        neo4j_client: Neo4jClient,
        cleanup_test_data: None,
    ) -> None:
        """create_node should return node properties as dict."""
        from klabautermann.core.ontology import NodeLabel

        properties = {
            "uuid": f"test-contract-node-{time.time()}",
            "name": "Contract Test Person",
            "created_at": time.time(),
            "updated_at": time.time(),
        }

        result = await neo4j_client.create_node(
            label=NodeLabel.PERSON,
            properties=properties,
        )

        assert isinstance(result, dict)
        assert result.get("uuid") == properties["uuid"]
        assert result.get("name") == "Contract Test Person"

    @pytest.mark.asyncio
    async def test_get_node_by_uuid_returns_dict_when_found(
        self,
        neo4j_client: Neo4jClient,
        cleanup_test_data: None,
    ) -> None:
        """get_node_by_uuid returns dict if node exists."""
        from klabautermann.core.ontology import NodeLabel

        node_uuid = f"test-contract-get-{time.time()}"
        properties = {
            "uuid": node_uuid,
            "name": "Test Person For Get",
            "created_at": time.time(),
            "updated_at": time.time(),
        }

        # Create node first
        await neo4j_client.create_node(NodeLabel.PERSON, properties)

        # Retrieve it
        result = await neo4j_client.get_node_by_uuid(
            label=NodeLabel.PERSON,
            uuid=node_uuid,
        )

        assert isinstance(result, dict)
        assert result.get("uuid") == node_uuid
        assert result.get("name") == "Test Person For Get"

    @pytest.mark.asyncio
    async def test_get_node_by_uuid_returns_none_when_not_found(
        self,
        neo4j_client: Neo4jClient,
    ) -> None:
        """get_node_by_uuid returns None if node doesn't exist."""
        from klabautermann.core.ontology import NodeLabel

        result = await neo4j_client.get_node_by_uuid(
            label=NodeLabel.PERSON,
            uuid="non-existent-uuid-12345",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_update_node_modifies_properties(
        self,
        neo4j_client: Neo4jClient,
        cleanup_test_data: None,
    ) -> None:
        """update_node should modify node properties."""
        from klabautermann.core.ontology import NodeLabel

        node_uuid = f"test-contract-update-{time.time()}"
        properties = {
            "uuid": node_uuid,
            "name": "Original Name",
            "created_at": time.time(),
            "updated_at": time.time(),
        }

        # Create node
        await neo4j_client.create_node(NodeLabel.PERSON, properties)

        # Update it
        result = await neo4j_client.update_node(
            label=NodeLabel.PERSON,
            uuid=node_uuid,
            properties={"name": "Updated Name"},
        )

        assert result is not None
        assert result.get("name") == "Updated Name"


@pytest.mark.integration
@requires_neo4j
class TestNeo4jRelationshipOperations:
    """Contract tests for Neo4j relationship operations."""

    @pytest.mark.asyncio
    async def test_create_relationship_returns_success(
        self,
        neo4j_client: Neo4jClient,
        cleanup_test_data: None,
    ) -> None:
        """create_relationship should return True on success."""
        from klabautermann.core.ontology import NodeLabel, RelationType

        ts = time.time()
        person_uuid = f"test-rel-person-{ts}"
        org_uuid = f"test-rel-org-{ts}"

        # Create nodes first
        await neo4j_client.create_node(
            NodeLabel.PERSON,
            {"uuid": person_uuid, "name": "Test Person", "created_at": ts, "updated_at": ts},
        )
        await neo4j_client.create_node(
            NodeLabel.ORGANIZATION,
            {"uuid": org_uuid, "name": "Test Org", "created_at": ts, "updated_at": ts},
        )

        # Create relationship
        result = await neo4j_client.create_relationship(
            from_label=NodeLabel.PERSON,
            from_uuid=person_uuid,
            rel_type=RelationType.WORKS_AT,
            to_label=NodeLabel.ORGANIZATION,
            to_uuid=org_uuid,
            properties={"title": "Engineer", "created_at": ts},
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_relationship_has_temporal_properties(
        self,
        neo4j_client: Neo4jClient,
        cleanup_test_data: None,
    ) -> None:
        """Relationships should support created_at and expired_at."""
        ts = time.time()

        # Create nodes and relationship via direct query
        await neo4j_client.execute_query(
            """
            CREATE (p:Person {uuid: $person_uuid, name: 'Test Person', created_at: $ts, updated_at: $ts})
            CREATE (o:Organization {uuid: $org_uuid, name: 'Test Org', created_at: $ts, updated_at: $ts})
            CREATE (p)-[:WORKS_AT {created_at: $created, expired_at: null, title: 'Engineer'}]->(o)
            """,
            {
                "person_uuid": f"test-temporal-person-{ts}",
                "org_uuid": f"test-temporal-org-{ts}",
                "ts": ts,
                "created": ts,
            },
        )

        # Query relationship with temporal properties
        result = await neo4j_client.execute_query(
            """
            MATCH (p:Person)-[r:WORKS_AT]->(o:Organization)
            WHERE p.uuid STARTS WITH 'test-temporal-person-'
            RETURN r.created_at as created, r.expired_at as expired, r.title as title
            """,
            {},
        )

        assert len(result) == 1
        assert result[0]["created"] == ts
        assert result[0]["expired"] is None
        assert result[0]["title"] == "Engineer"


@pytest.mark.integration
@requires_neo4j
class TestNeo4jFindOperations:
    """Contract tests for Neo4j find operations."""

    @pytest.mark.asyncio
    async def test_find_nodes_returns_list(
        self,
        neo4j_client: Neo4jClient,
        cleanup_test_data: None,
    ) -> None:
        """find_nodes should return list of node dicts."""
        from klabautermann.core.ontology import NodeLabel

        ts = time.time()
        # Create a node to find
        await neo4j_client.create_node(
            NodeLabel.PERSON,
            {
                "uuid": f"test-find-{ts}",
                "name": "Findable Person",
                "email": "findable@test.com",
                "created_at": ts,
                "updated_at": ts,
            },
        )

        # Find it
        result = await neo4j_client.find_nodes(
            label=NodeLabel.PERSON,
            properties={"email": "findable@test.com"},
        )

        assert isinstance(result, list)
        assert len(result) >= 1
        assert any(n.get("name") == "Findable Person" for n in result)
