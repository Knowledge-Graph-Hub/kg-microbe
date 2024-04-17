echo "Building Neo4j Artifact"
docker rm -f neo || True
#tar -C output -xzf output/monarch-kg.jsonl.tar.gz
mkdir neo4j-data
docker run -d --name neo -p7474:7474 -p7687:7687 -v neo4j-data:/data --env NEO4J_AUTH=neo4j/admin neo4j:4.4
poetry run kgx transform --transform-config neo4j-transform.yaml > kgx-transform.log
docker stop neo
docker run -v $(pwd)/output:/backup -v neo4j-v4-data:/data --entrypoint neo4j-admin neo4j:4.4 dump --to /backup/kg-microbe.neo4j.dump
#rm output/monarch-kg_nodes.jsonl
#rm output/monarch-kg_edges.jsonl
