MATCH (l:Law {name: '中华人民共和国公司法'}) DETACH DELETE l;;
CREATE (l:Law {name: '中华人民共和国公司法', version: '2023年修订', effective_date: '2024-07-01'});