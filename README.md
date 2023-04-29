# hokatsu-backend

## How to setup dev env
- Spin up a dynamoDB local env with `docker-compose up`
- Create a table named `ota`
- Create a docker network with `docker network create :name`
- Run `sam build && sam local invoke --docker-network :name`