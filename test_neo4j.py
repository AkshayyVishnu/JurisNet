"""Quick Neo4j connectivity check. Run: python test_neo4j.py"""
from neo4j import GraphDatabase
from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

print(f"Connecting to {NEO4J_URI} as {NEO4J_USER} ...")
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
try:
    driver.verify_connectivity()
    with driver.session() as session:
        msg = session.run("RETURN 'Neo4j connection OK' AS msg").single()["msg"]
    print(msg)
finally:
    driver.close()
