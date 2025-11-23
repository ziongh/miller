# Miller - TODO

*Last updated: 2025-11-23*

<!-- Add your notes below -->

1. Deep review project startup indexing, incremental indexing, and the manage_workspace functionality. This is foundation of the whole system. Let's dig in and ultrathink about it and do a close compare to ~/source/julie functionality for the same things: startup, incremental, manage_workspace. Obviously we will be a LITTLE different from julie because of our tech stack differences but Julie has had a lot more dogfooding done on it than Miller and that's a theme that's going to be recurring. So while we aren't going to straight copy Julie (we actually want to improve upon Julie in every aspect that we can) we do want to leverage Julie's lessons learned from more extensive dogfooding.

2. This is really an extension of #1: we need to audit the data we are capturing and where we are storing it. Treesitter extracted data, filenames, filepaths, file content, positional data, relationships, lance indexes, etc. We want to make sure we are at least covering the same data as Julie and then we want to improve upon that. We have lance/tantivy available and that opens up so many more opportunities than we had in Julie. We can create mulitple indexed fields with different tokenizers, whatever we need to do. The extractors are the heart of the project but the resulting data, the indexes, the embeddings, are all the life blood of project and we need to insure that it is of the utmost quality.

3. We need to check the issues on github in Julie, a user posted a comment there about RAG and embeddings that I want us to discuss.

4. I think we should look at the plan tool and discuss how we can enhance it. I noticed that in use, our plans get pretty large, which is fine, but the issue is that our read/update mechanism for plans isn't very token efficient and we start getting token size warnings pretty quickly. Also, in my mind a "task" or list of "tasks" is a fundamental part of a plan and it would be nice if we could enhance the tool to make management of tasks easy. Again we should disucss and zero in on the best way to handle this.

5. In Julie we created a set of rules to follow when auditing each tool and then went one by one validating each tool (/Users/murphy/source/julie/docs/archive/TOOL_AUDIT_2025-11-11_COMPLETE.md) we should do something similar in Miller to make sure that every tool is leveraging our unique functionality to highest level it can. Also part of this audit should be the specialized output formats. Another point: as we audit the tools we should explore how Julie implemented the same tool, not to copy it but make sure that Julie hasn't already solved some issue we haven't encountered yet or maybe Julie has some genuinely clever implementation we can build on.

6. We should look at the skills defined in Julie and create our own version for Miller ~/source/julie/.claude/skills https://code.claude.com/docs/en/skills

7. We have some custom commands we've created at .claude/commands, we should discuss if there are others we should add. We should also discuss if there are any hooks we should create https://code.claude.com/docs/en/hooks-guide

