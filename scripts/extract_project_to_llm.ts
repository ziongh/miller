// eslint-disable no-eq-null
// eslint-disable eqeqeq
// eslint-disable no-map-spread
// eslint-disable no-explicit-any
// eslint-disable prefer-optional-catch-binding
// eslint-disable no-continue
// eslint-disable prefer-regexp-test
import fs from 'node:fs';
import path from 'node:path';
import { Glob, file, write } from 'bun';

// --- Configuration ---
const outputFileName = 'llm_extracted_content.txt';

// Globs to exclude. These are relative to the project root.
// The glob "*/**" for inclusion will pick up base folder files (e.g., package.json)
// unless they are explicitly excluded here.
const excludeGlobs: string[] = [
	'**/node_modules/**',
	'**/dist/**',
	'**/.git/**',
	'**/.vscode/**',
	'**/.idea/**',
	'**/*.log',
	'**/*.lock',
	'**/bun.lockb',
	'**/*.DS_Store',
	'**/*.env',
	'**/.env.*',
	'**/coverage/**',
	'**/*.bak',
	'**/*.tmp',
	'**/*.swp',
	`**/${outputFileName}`, // Exclude the output file itself!
	'**/public/vite.svg',
	'**/*.ico',
	'**/*.png',
	'**/*.jpg',
	'**/*.jpeg',
	'**/*.gif',
	// "**/*.svg", // Uncomment if you want to exclude SVG XML content
	'**/*.woff',
	'**/*.woff2',
	'**/*.ttf',
	'**/*.eot',
	'**/*.min.js',
	'**/build/**', // Exclude build directories
	'**/obj/**', // Exclude build directories
	'**/bin/**', // Exclude build directories
	'**/SQL/**', // Exclude build directories
	'**/99_UtilSqlScripts/**', // Exclude build directories
	'**/Properties/**', // Exclude build directories
	'**/Resources/**', // Exclude build directories
	'**/snapshots/**', // Exclude build directories
	'**/wwwroot/**', // Exclude build directories
	'**/Migrations/**', // Exclude build directories
	'**/*.svg', // Exclude build directories
	'**/*.csv', // Exclude build directories
	'**/*.xls', // Exclude build directories
	'**/*.xlsm', // Exclude build directories
	'**/*.xlsb', // Exclude build directories
	'**/*.CNAB', // Exclude build directories
	'**/*.toml', // Exclude build directories
	'**/*.txt', // Exclude build directories
	'**/*.xlsx', // Exclude build directories
	'**/*.so', // Exclude build directories
	'**/*.zip', // Exclude build directories
	'**/*.REM', // Exclude build directories
	'**/*.RET', // Exclude build directories
	'**/*.whl', // Exclude build directories
	'tsconfig.tsbuildinfo',
	'README.md',
	'**/.coverage/**',
	'**/.claude/**',
	'**/.github/**',
	'**/.vscode/**',
	'**/.memories/**',
	'**/.miller/**',
	'**/.pytest_cache/**',
	'**/.venv/**',
	'**/test_samples/**',
	'**/tests/**',
	'**/htmlcov/**',
	'**/target/**',
	'**/__pycache__/**',
	'**/llm_extracted_content.txt', // Exclude the output file itself
];

// Configuration for truncating specific files
interface TruncateRule {
	globPattern: string; // Glob pattern to match files
	maxLines: number; // Maximum number of lines to keep
	truncationMessage: string; // Message to append after truncation
}

const truncateFilesConfig: TruncateRule[] = [
	{
		globPattern: '**/swagger.json', // For your OpenAPI JSON
		maxLines: 70,
		truncationMessage:
			'\n\n... [Content Truncated due to length. Full file available in repository.] ...',
	},
	{
		globPattern: '**/generated.ts', // Example for potentially long generated TS files
		maxLines: 1200,
		truncationMessage: '\n\n... [Generated TypeScript Content Truncated] ...',
	},
];
// --- End Configuration ---

// Pre-compile glob matchers for efficiency
const excludeMatchers = excludeGlobs.map((pattern) => new Glob(pattern));
const compiledTruncateRules = truncateFilesConfig.map((rule) => ({
	...rule,
	globMatcher: new Glob(rule.globPattern),
}));

async function main() {
	console.log('Starting project content extraction...');

	const projectRoot = process.cwd();
	let allFormattedContent = '';
	let fileCount = 0;
	let excludedCount = 0;
	let truncatedFileCount = 0;

	// This glob "*/**" will scan all files and directories,
	// including those in the base/root folder of the project.
	const includeScanner = new Glob('*/**');
	const baseFiles = new Glob('*');

	for await (const relativeFilePath of combine([
		includeScanner.scan('.'),
		baseFiles.scan('.'),
	])) {
		const absoluteFilePath = path.join(projectRoot, relativeFilePath);

		try {
			const stats = fs.statSync(absoluteFilePath);
			if (!stats.isFile()) {
				continue;
			}
		} catch (e) {
			console.warn(`Could not stat (skipping): ${relativeFilePath}`);
			continue;
		}

		let isExcluded = false;
		for (const matcher of excludeMatchers) {
			if (matcher.match(relativeFilePath)) {
				isExcluded = true;
				break;
			}
		}

		if (isExcluded) {
			excludedCount += 1;
			continue;
		}

		try {
			let fileContentToProcess = '';
			let truncationNotice = '';
			let appliedTruncationRuleDetails: { maxLines: number } | null = null;

			// Check for truncation rules
			let matchedRuleConfig: TruncateRule | undefined = undefined;
			for (const rule of compiledTruncateRules) {
				if (rule.globMatcher.match(relativeFilePath)) {
					matchedRuleConfig = rule;
					break; // First matching rule applies
				}
			}

			const fullFileText = await file(absoluteFilePath).text(); // Can throw for binary

			if (matchedRuleConfig) {
				const lines = fullFileText.split('\n');
				if (lines.length > matchedRuleConfig.maxLines) {
					fileContentToProcess =
						lines.slice(0, matchedRuleConfig.maxLines).join('\n') +
						matchedRuleConfig.truncationMessage;
					truncationNotice = ` (truncated to ${matchedRuleConfig.maxLines} lines)`;
					appliedTruncationRuleDetails = {
						maxLines: matchedRuleConfig.maxLines,
					};
					truncatedFileCount += 1;
				} else {
					fileContentToProcess = fullFileText; // File is shorter than maxLines
				}
			} else {
				fileContentToProcess = fullFileText;
			}

			const normalizedRelativePath = relativeFilePath.split(path.sep).join('/');
			const formattedBlock = `--- START OF FILE ${normalizedRelativePath}${truncationNotice} ---\n\n${fileContentToProcess}\n\n--- END OF FILE ${normalizedRelativePath} ---\n\n`;
			allFormattedContent += formattedBlock;
			fileCount += 1;

			if (fileCount % 100 === 0) {
				console.log(`Processed ${fileCount} files...`);
			}
		} catch (error: any) {
			if (error.message?.includes('invalid utf-8')) {
				console.warn(`Skipping binary or non-UTF-8 file: ${relativeFilePath}`);
			} else {
				console.warn(
					`Could not read/process file ${relativeFilePath}: ${error.message}`,
				);
			}
			excludedCount += 1;
		}
	}

	console.log('\nExtraction complete.');
	console.log(`Included ${fileCount} files.`);
	if (truncatedFileCount > 0) {
		console.log(`Truncated ${truncatedFileCount} files according to rules.`);
	}
	console.log(
		`Excluded/Skipped ${excludedCount} files/directories or unreadable files.`,
	);

	if (fileCount > 0) {
		await write(outputFileName, allFormattedContent);
		console.log(`Output written to ${outputFileName}`);
	} else {
		console.log('No files were included. Output file not written.');
	}
}

main().catch(console.error);

async function* combine(iterable) {
	const asyncIterators = Array.from(iterable, (o: any) =>
		o[Symbol.asyncIterator](),
	);
	const results: any[] = [];
	let count = asyncIterators.length;
	// eslint-disable-next-line no-empty-function
	const never = new Promise(() => {});
	// eslint-disable-next-line consistent-function-scoping
	function getNext(asyncIterator, index) {
		return asyncIterator.next().then((result) => ({
			index,
			result,
		}));
	}
	const nextPromises = asyncIterators.map(getNext);
	try {
		while (count) {
			// eslint-disable-next-line no-await-in-loop
			const { index, result } = await Promise.race(nextPromises);
			if (result.done) {
				nextPromises[index] = never;
				results[index] = result.value;
				// eslint-disable-next-line no-plusplus
				count--;
			} else {
				nextPromises[index] = getNext(asyncIterators[index], index);
				yield result.value;
			}
		}
	} finally {
		for (const [index, iterator] of asyncIterators.entries()) {
			// biome-ignore lint/suspicious/noDoubleEquals: <explanation>
			if (nextPromises[index] != never && iterator.return != null) {
				iterator.return();
			}
		}
		// no await here - see https://github.com/tc39/proposal-async-iteration/issues/126
	}
	return results;
}
