# gitlab2gitea
Import issues, comments and their atachements from Gitlab to Gitea

## Configuration
In config.py set important settings: web pages, user names, API keys, MYSQL, ...

## Run
Run gitlab2gitea.py

## ToDo
Code is designed to import issues in the order they are created to keep their number, but if some issue is deleted it will not porbably work. I did not implemented creation of "auxiliary" issues.

Code is very dirty as I put it together with assistance of chatGPT

## References
In case of need look at API documentation, for example:
- https://docs.gitea.com/api/1.20/#tag/issue/operation/issueListIssueAttachments
- https://docs.gitea.com/api/1.20/#tag/issue/operation/issueListIssueCommentAttachments
- https://docs.gitlab.com/api/projects/
