"""

"""

import tensorflow as tf


def scaled_dot_product_attention(q, k, v, mask):
    """
    Calculate the attention weights.
    q, k, v must have matching leading dimensions.
    k, v must have matching penultimate dimension, i.e.: seq_len_k = seq_len_v.
    The mask has different shapes depending on its type(padding or look ahead)
    but it must be broadcastable for addition.

    Args:
      q: query shape == (..., seq_len_q, depth)
      k: key shape == (..., seq_len_k, depth)
      v: value shape == (..., seq_len_v, depth_v)
      mask: Float tensor with shape broadcastable
            to (..., seq_len_q, seq_len_k). Defaults to None.

    Returns:
      output, attention_weights
    """

    matmul_qk = tf.matmul(q, k, transpose_b=True)  # (..., seq_len_q, seq_len_k)

    # scale matmul_qk
    dk = tf.cast(tf.shape(k)[-1], tf.float32)
    scaled_attention_logits = matmul_qk / tf.math.sqrt(dk)

    # add the mask to the scaled tensor.
    if mask is not None:
        scaled_attention_logits += (mask * -1e9)

    # softmax is normalized on the last axis (seq_len_k) so that the scores
    # add up to 1.
    attention_weights = tf.nn.softmax(scaled_attention_logits, axis=-1)  # (..., seq_len_q, seq_len_k)

    output = tf.matmul(attention_weights, v)  # (..., seq_len_q, depth_v)

    return output, attention_weights


class MultiHeadAttention(tf.keras.layers.Layer):
    """
    """
    def __init__(self, d_model, num_heads):
        super(MultiHeadAttention, self).__init__()
        self.num_heads = num_heads
        self.d_model = d_model

        assert d_model % self.num_heads == 0

        self.depth = d_model // self.num_heads

        self.wq = tf.keras.layers.Dense(d_model)
        self.wk = tf.keras.layers.Dense(d_model)
        self.wv = tf.keras.layers.Dense(d_model)

        self.dense = tf.keras.layers.Dense(d_model)

    def split_heads(self, x, batch_size):
        """
        Split the last dimension into (num_heads, depth).
        Transpose the result such that the shape is (batch_size, num_heads, seq_len, depth)
        """
        x = tf.reshape(x, (batch_size, -1, self.num_heads, self.depth))
        return tf.transpose(x, perm=[0, 2, 1, 3])

    def call(self, v, k, q, mask):
        batch_size = tf.shape(q)[0]

        q = self.wq(q)  # (batch_size, seq_len, d_model)
        k = self.wk(k)  # (batch_size, seq_len, d_model)
        v = self.wv(v)  # (batch_size, seq_len, d_model)

        q = self.split_heads(q, batch_size)  # (batch_size, num_heads, seq_len_q, depth)
        k = self.split_heads(k, batch_size)  # (batch_size, num_heads, seq_len_k, depth)
        v = self.split_heads(v, batch_size)  # (batch_size, num_heads, seq_len_v, depth)

        # scaled_attention.shape == (batch_size, num_heads, seq_len_q, depth)
        # attention_weights.shape == (batch_size, num_heads, seq_len_q, seq_len_k)
        scaled_attention, attention_weights = scaled_dot_product_attention(
            q, k, v, mask)

        scaled_attention = tf.transpose(scaled_attention,
                                        perm=[0, 2, 1, 3])  # (batch_size, seq_len_q, num_heads, depth)

        concat_attention = tf.reshape(scaled_attention,
                                      (batch_size, -1, self.d_model))  # (batch_size, seq_len_q, d_model)

        output = self.dense(concat_attention)  # (batch_size, seq_len_q, d_model)

        return output, attention_weights


class PointWiseFFN(tf.keras.layers.Layer):
    def __init__(self, d_model, rate=0.1):
        super(PointWiseFFN, self).__init__()

        self.conv1d_1 = tf.keras.layers.Conv1D(d_model, kernel_size=1, activation='relu')
        self.conv1d_2 = tf.keras.layers.Conv1D(d_model, kernel_size=1, activation='relu')

        self.dropout = tf.keras.layers.Dropout(rate)

    def call(self, x, training):
        out = self.conv1d_1(x)
        out = self.dropout(out, training=training)
        out = self.conv1d_2(out)

        return out


# def point_wise_feed_forward_network(d_model, training, dropout_rate=0.2):
#     # self.conv1 = torch.nn.Conv1d(hidden_units, hidden_units, kernel_size=1)
#     # self.dropout1 = torch.nn.Dropout(p=dropout_rate)
#     # self.relu = torch.nn.ReLU()
#     # self.conv2 = torch.nn.Conv1d(hidden_units, hidden_units, kernel_size=1)
#     # self.dropout2 = torch.nn.Dropout(p=dropout_rate)
#
#     return tf.keras.Sequential([
#         tf.keras.layers.Conv1D(d_model, kernel_size=1, activation='relu'),
#         tf.keras.layers.Dropout(rate=dropout_rate, trainable=training),# (batch_size, seq_len, dff)
#         tf.keras.layers.Conv1D(d_model, kernel_size=1, activation='relu') # input_shape=input_shape[1:]
#         # tf.keras.layers.Dropout(rate=dropout_rate)  # (batch_size, seq_len, dff)
#     ])


class SASEncoderLayer(tf.keras.layers.Layer):
    def __init__(self, d_model, num_heads, rate=0.1):
        super(SASEncoderLayer, self).__init__()

        self.mha = MultiHeadAttention(d_model, num_heads)
        self.ffn = PointWiseFFN(d_model, rate)

        self.layernorm1 = tf.keras.layers.LayerNormalization(epsilon=1e-6)
        self.layernorm2 = tf.keras.layers.LayerNormalization(epsilon=1e-6)

        self.dropout1 = tf.keras.layers.Dropout(rate)
        self.dropout2 = tf.keras.layers.Dropout(rate)

    def call(self, x, training, mask):
        attn_output, _ = self.mha(x, x, x, mask)  # (batch_size, input_seq_len, d_model)
        attn_output = self.dropout1(attn_output, training=training)
        out1 = self.layernorm1(x + attn_output)  # (batch_size, input_seq_len, d_model)

        ffn_output = self.ffn(out1, training=training)  # (batch_size, input_seq_len, d_model)
        ffn_output = self.dropout2(ffn_output, training=training)
        out2 = self.layernorm2(out1 + ffn_output)  # (batch_size, input_seq_len, d_model)

        return out2


class SASEncoder(tf.keras.layers.Layer):
    def __init__(self, num_layers, d_model, num_heads, input_vocab_size,
                 max_len, rate=0.1, l2_emb=0.0):
        super(SASEncoder, self).__init__()

        self.d_model = d_model
        self.num_layers = num_layers

        self.embedding = tf.keras.layers.Embedding(input_vocab_size, d_model, mask_zero=True,
                                                   embeddings_regularizer=tf.keras.regularizers.l2(l2_emb))
        self.pos_embedding = tf.keras.layers.Embedding(max_len, d_model,
                                                       embeddings_regularizer=tf.keras.regularizers.l2(l2_emb))

        self.enc_layers = [SASEncoderLayer(d_model, num_heads, rate)
                           for _ in range(num_layers)]

        self.dropout = tf.keras.layers.Dropout(rate)

    def call(self, x, training, mask):
        seq_len = tf.shape(x)[1]

        # adding embedding and position encoding.
        x = self.embedding(x)  # (batch_size, input_seq_len, d_model)
        x *= tf.math.sqrt(tf.cast(self.d_model, tf.float32))
        x_pos = tf.tile(tf.expand_dims(tf.range(tf.shape(x)[1]), 0), [tf.shape(x)[0], 1])
        x += self.pos_embedding(x_pos)

        x = self.dropout(x, training=training)

        for i in range(self.num_layers):
            x = self.enc_layers[i](x, training, mask)

        return x  # (batch_size, input_seq_len, d_model)
