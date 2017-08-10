import trainer
from data_processing.document_splitter import MergeParagraphs, TopTfIdf
from data_processing.preprocessed_corpus import PreprocessedData
from data_processing.qa_data import FixedParagraphQaTrainingData, Batcher
from data_processing.text_utils import NltkPlusStopWords
from doc_qa_models import Attention
from encoder import DocumentAndQuestionEncoder, SingleSpanAnswerEncoder, DenseMultiSpanAnswerEncoder
from evaluator import LossEvaluator
from nn.attention import StaticAttention, StaticAttentionSelf, AttentionEncoder
from nn.embedder import FixedWordEmbedder, CharWordEmbedder, LearnedCharEmbedder
from nn.layers import NullBiMapper, NullMapper, SequenceMapperSeq, DropoutLayer, FullyConnected, ChainBiMapper, \
    ConcatWithProduct, WithProjectedProduct, \
    MapperSeq, ResidualLayer
from nn.recurrent_layers import BiRecurrentMapper, RecurrentEncoder, EncodeOverTime, GruCellSpec
from nn.similarity_layers import TriLinear
from nn.span_prediction import WithFixedContextPredictionLayer
from trainer import SerializableOptimizer, TrainParams
from squad.squad import SquadCorpus

from squad.squad_eval import BoundedSquadSpanEvaluator
from trivia_qa.build_span_corpus import TriviaQaWebDataset
from trivia_qa.lazy_data import LazyRandomParagraphBuilder
from trivia_qa.triviaqa_evaluators import TfTriviaQaBoundedSpanEvaluator
from utils import get_output_name_from_cli


def main():
    out = get_output_name_from_cli()

    train_params = TrainParams(SerializableOptimizer("Adadelta", dict(learning_rate=1.0)),
                               ema=0.999, max_checkpoints_to_keep=3,
                               num_epochs=30, log_period=30, eval_period=1200, save_period=1200,
                               eval_samples=dict(dev=None, train=8000))

    enc = SequenceMapperSeq(
        DropoutLayer(0.8),
        BiRecurrentMapper(GruCellSpec(80)),
        DropoutLayer(0.8),
    )

    model = Attention(
        encoder=DocumentAndQuestionEncoder(DenseMultiSpanAnswerEncoder()),
        word_embed_layer=None,
        word_embed=FixedWordEmbedder(vec_name="glove.840B.300d", word_vec_init_scale=0, learn_unk=False),
        char_embed=CharWordEmbedder(
            LearnedCharEmbedder(word_size_th=14, char_th=50, char_dim=15, init_scale=0.1),
            EncodeOverTime(RecurrentEncoder(GruCellSpec(50), None), mask=True),
            shared_parameters=True
        ),
        embed_mapper=enc,
        question_mapper=None,
        context_mapper=None,
        memory_builder=NullBiMapper(),
        attention=StaticAttention(TriLinear(bias=True), ConcatWithProduct()),
        # attention=BiAttention(TriLinear(bias=True), True),
        match_encoder=SequenceMapperSeq(
            FullyConnected(160, activation="tanh"),
            DropoutLayer(0.8),
            BiRecurrentMapper(GruCellSpec(80)),
            DropoutLayer(0.8),
            StaticAttentionSelf(TriLinear(bias=True), ConcatWithProduct()),
            FullyConnected(160, activation="tanh"),
            DropoutLayer(0.8),
        ),
        predictor=WithFixedContextPredictionLayer(
            ResidualLayer(BiRecurrentMapper(GruCellSpec(80))),
            AttentionEncoder(post_process=MapperSeq(FullyConnected(25, activation="tanh"), DropoutLayer(0.8))),
            WithProjectedProduct(include_tiled=True),
            ChainBiMapper(
                first_layer=BiRecurrentMapper(GruCellSpec(80)),
                second_layer=BiRecurrentMapper(GruCellSpec(80))
            ),
            aggregate="sum"
        )
    )
    with open(__file__, "r") as f:
        notes = f.read()

    corpus = SquadCorpus()
    train_batching = Batcher(45, "bucket_context_words_3", True, False)
    eval_batching = Batcher(45, "context_words", False, False)
    data = FixedParagraphQaTrainingData(corpus, None, train_batching, eval_batching)

    eval = [LossEvaluator(), BoundedSquadSpanEvaluator(bound=[17])]
    trainer.start_training(data, model, train_params, eval, trainer.ModelDir(out), notes, False)


if __name__ == "__main__":
    main()