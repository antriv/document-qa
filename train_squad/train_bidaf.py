import trainer
from data_processing.paragraph_qa import ContextLenKey, ContextLenBucketedKey
from data_processing.qa_data import FixedParagraphQaTrainingData, Batcher
from dataset import ShuffledBatcher, ClusteredBatcher
from doc_qa_models import Attention
from encoder import DocumentAndQuestionEncoder, SingleSpanAnswerEncoder
from evaluator import LossEvaluator, SpanEvaluator, SentenceSpanEvaluator
from nn.attention import BiAttention
from nn.embedder import FixedWordEmbedder, CharWordEmbedder, LearnedCharEmbedder
from nn.layers import NullBiMapper, NullMapper, SequenceMapperSeq, ReduceLayer, Conv1d, HighwayLayer
from nn.prediction_layers import ChainConcatPredictor
from nn.recurrent_layers import BiRecurrentMapper, LstmCellSpec
from nn.similarity_layers import TriLinear
from trainer import SerializableOptimizer, TrainParams
from squad.squad import SquadCorpus
from utils import get_output_name_from_cli


def main():
    """
    A close-as-possible impelemntation of BiDaF, its based on the `dev` tensorflow 1.1 branch of Ming's repo
    which, in particular, uses Adam not Adadelta. I was not able to replicate the results in paper using Adadelta,
    but with Adam i was able to get to 78.0 F1 on the dev set with this scripts. I believe this approach is
    an exact reproduction up the code in the repo, up to initializations.

    Notes: Exponential Moving Average is very important, as is early stopping. This is also in particualr best run
    on a GPU due to the large number of parameters and batch size involved.
    """
    out = get_output_name_from_cli()

    train_params = TrainParams(SerializableOptimizer("Adam", dict(learning_rate=0.001)),
                               num_epochs=12, ema=0.999,
                               log_period=30, eval_period=1000, save_period=1000,
                               eval_samples=dict(dev=None, train=8000))

    model = Attention(
        encoder=DocumentAndQuestionEncoder(SingleSpanAnswerEncoder()),
        word_embed=FixedWordEmbedder(vec_name="glove.6B.100d", word_vec_init_scale=0, learn_unk=False),
        char_embed=CharWordEmbedder(
            embedder=LearnedCharEmbedder(16, 49, 8),
            layer=ReduceLayer("max", Conv1d(100, 5, 0.8)),
            shared_parameters=True
        ),
        word_embed_layer=None,
        embed_mapper=SequenceMapperSeq(
            HighwayLayer(activation="relu"), HighwayLayer(activation="relu"),
            BiRecurrentMapper(LstmCellSpec(100, keep_probs=0.8))),
        question_mapper=None,
        context_mapper=None,
        memory_builder=NullBiMapper(),
        attention=BiAttention(TriLinear(bias=True), True),
        match_encoder=NullMapper(),
        predictor= ChainConcatPredictor(
            start_layer=SequenceMapperSeq(
                BiRecurrentMapper(LstmCellSpec(100, keep_probs=0.8)),
                BiRecurrentMapper(LstmCellSpec(100, keep_probs=0.8))),
            end_layer=BiRecurrentMapper(LstmCellSpec(100, keep_probs=0.8))
        )
    )

    with open(__file__, "r") as f:
        notes = f.read()

    eval = [LossEvaluator(), SpanEvaluator(), SentenceSpanEvaluator()]

    corpus = SquadCorpus()
    train_batching = ClusteredBatcher(60, ContextLenBucketedKey(3), True, False)
    eval_batching = ClusteredBatcher(60, ContextLenKey(), False, False)
    data = FixedParagraphQaTrainingData(corpus, None, train_batching, eval_batching)

    trainer.start_training(data, model, train_params, eval, trainer.ModelDir(out), notes, False)


if __name__ == "__main__":
    main()