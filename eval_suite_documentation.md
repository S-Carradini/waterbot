WaterBot RAG Evaluation Suite Documentation

This document explains the testing suite we built to evaluate the WaterBot RAG pipeline. The goal of this suite is to give us a reliable way to measure how well the bot finds information and generates answers, especially when we add new knowledge sources. 

System Overview and Methodology:

We decided to build this suite as a set of standalone Python scripts separate from the main application code. This keeps our production deployment lightweight and ensures that testing logic doesn't interfere with the actual bot. We split the evaluation into two main parts because finding the right document (retrieval) and generating a good answer from it (generation) are two different problems. If the bot gives a bad answer, we need to know if it's because it couldn't find the right PDF, or if it found the PDF but just hallucinated the response.

To test this, we put together a benchmark dataset with 60 representative questions covering different topics like general policy, numeric extraction, and multi-hop reasoning. We also included some out-of-scope questions to make sure the bot knows when to refuse to answer. Each question is mapped to the exact PDFs needed to answer it.

When we run the retrieval evaluation, the script queries the vector database and checks if the chunks it pulls back actually match the required PDFs for that question. We measure this using standard metrics like Recall@k and MRR. Then, for the generation evaluation, we run the full pipeline and use the RAGAS framework. RAGAS basically uses an LLM to grade the bot's answers based on faithfulness to the text and overall correctness. We also added a custom check to make sure the bot doesn't hallucinate answers for things it shouldn't know about.

Why We Chose This Approach:

We went with custom Python scripts and the open-source RAGAS framework because it gives us full control. We completely avoided heavy enterprise platforms like LangSmith or Arize. Those tools usually come with steep learning curves, vendor lock-in, and high monthly costs. Our setup is essentially free, running entirely on our own infrastructure, minus the basic OpenAI API costs for the grading LLM.

We also didn't want to rely on Jupyter Notebooks or manual testing. Manual testing is subjective and doesn't scale when you need to test 60 questions every time you add a PDF. Notebooks are notoriously hard to integrate into automated CI/CD pipelines. The scripts we wrote can be run locally or hooked up to GitHub Actions to automatically run whenever code changes.

How to Run the Suite:

Before running anything, make sure your local Docker database is running and you have installed the dependencies from the eval/requirements-eval.txt file. You'll also need a valid OpenAI API key in your environment.

To test just the retrieval part of the system, run the retrieval_metrics.py script in the eval directory. This runs very quickly because it just queries the database and doesn't make any LLM calls.

If you want to test the full pipeline and grade the answers, run the generation_metrics.py script. This will take a bit longer since it involves generating responses and grading them via the OpenAI API.

For a full automated check, you can run the run_eval_suite.py script. This runs both evaluations and checks the final scores against a set of minimum thresholds we defined in the thresholds.yaml file. It will fail if the system's performance drops below those acceptable levels.

We also included a load_test.py script. You can run this to simulate a bunch of users hitting the pipeline at the same time, which helps us understand our latency and find bottlenecks.

Interpreting the Results:

After running the scripts, you'll see the results printed to your console, and detailed summaries will be saved in the eval/results directory. 

For the retrieval metrics, the most important number is Recall@4. This tells you what percentage of the required documents were actually found in the top 4 search results. If this number is low, the LLM won't have the context it needs to generate a good answer. You don't need to worry as much about precision, as long as the correct documents are being found.

For the generation metrics, you want to look closely at Faithfulness and Answer Correctness. Faithfulness measures whether the bot's answer is strictly based on the provided documents. If it's low, the bot is hallucinating. Answer Correctness just measures how accurately it answered the original question. We also track the Hallucination on Negatives Rate, which should ideally be zero, meaning the bot successfully refused to answer all out-of-scope questions.

Files Involved:

Everything related to this suite is contained in the eval directory.

The benchmark_dataset.json file holds all our test questions and expected sources. The main testing logic lives in retrieval_metrics.py and generation_metrics.py. 

For automation and comparison, run_eval_suite.py handles the CI checks using the rules in thresholds.yaml. We also have an ablation_runner.py script that lets us run A/B tests to compare different database configurations, like seeing how the system performs before and after adding new PDFs. 

The config.py file handles some shared setup like database connections, and load_test.py is there for performance benchmarking. All the results get dumped into the results folder.
